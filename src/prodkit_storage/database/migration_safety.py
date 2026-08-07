"""Conservative static safety checks for Alembic revision files.

The linter intentionally focuses on operations that commonly create production
outages: destructive schema changes, blocking index creation, immediately
validated constraints on populated tables, and table-rewrite style changes.
It is a guardrail, not a PostgreSQL parser or substitute for migration review.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MigrationSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MigrationSafetyIssue:
    code: str
    severity: MigrationSeverity
    line: int
    message: str


class MigrationSafetyError(RuntimeError):
    def __init__(self, issues: tuple[MigrationSafetyIssue, ...]) -> None:
        self.issues = issues
        summary = "; ".join(f"{item.code}@{item.line}: {item.message}" for item in issues)
        super().__init__(summary)


@dataclass(frozen=True, slots=True)
class MigrationSafetyReport:
    path: str
    issues: tuple[MigrationSafetyIssue, ...]
    waivers: frozenset[str]

    @property
    def blocking_issues(self) -> tuple[MigrationSafetyIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity is MigrationSeverity.ERROR and issue.code not in self.waivers
        )

    @property
    def safe(self) -> bool:
        return not self.blocking_issues


_DESTRUCTIVE_OPS = {
    "drop_table",
    "drop_column",
    "drop_constraint",
    "drop_index",
}


def inspect_migration_source(
    source: str,
    *,
    path: str = "<memory>",
) -> MigrationSafetyReport:
    """Inspect the ``upgrade`` function in one Alembic revision source file.

    A revision may explicitly waive a finding by declaring a module-level
    ``migration_safety_allow`` set/list/tuple of finding codes. Waivers remain
    visible in the report and should be justified in review.
    """

    tree = ast.parse(source, filename=path)
    waivers = _extract_waivers(tree)
    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "upgrade"
        ),
        None,
    )
    if upgrade is None:
        return MigrationSafetyReport(
            path=path,
            issues=(
                MigrationSafetyIssue(
                    code="missing-upgrade",
                    severity=MigrationSeverity.ERROR,
                    line=1,
                    message="Alembic revision does not define upgrade()",
                ),
            ),
            waivers=waivers,
        )

    scanner = _UpgradeScanner(source)
    scanner.scan_block(upgrade.body, autocommit=False)
    return MigrationSafetyReport(path=path, issues=tuple(scanner.issues), waivers=waivers)


def inspect_migration_file(path: str | Path) -> MigrationSafetyReport:
    file_path = Path(path)
    source = file_path.read_text(encoding="utf-8")
    return inspect_migration_source(source, path=str(file_path))


def assert_migration_file_safe(path: str | Path) -> MigrationSafetyReport:
    report = inspect_migration_file(path)
    if report.blocking_issues:
        raise MigrationSafetyError(report.blocking_issues)
    return report


class _UpgradeScanner:
    def __init__(self, source: str) -> None:
        self.source = source
        self.created_tables: set[str] = set()
        self.issues: list[MigrationSafetyIssue] = []

    def scan_block(self, statements: list[ast.stmt], *, autocommit: bool) -> None:
        for statement in statements:
            if isinstance(statement, ast.With):
                nested_autocommit = autocommit or any(
                    _is_autocommit_context(item.context_expr) for item in statement.items
                )
                self.scan_block(statement.body, autocommit=nested_autocommit)
                continue
            if isinstance(statement, ast.If):
                self.scan_block(statement.body, autocommit=autocommit)
                self.scan_block(statement.orelse, autocommit=autocommit)
                continue
            if isinstance(statement, (ast.For, ast.While, ast.Try)):
                self.scan_block(statement.body, autocommit=autocommit)
                if isinstance(statement, ast.Try):
                    for handler in statement.handlers:
                        self.scan_block(handler.body, autocommit=autocommit)
                    self.scan_block(statement.orelse, autocommit=autocommit)
                    self.scan_block(statement.finalbody, autocommit=autocommit)
                else:
                    self.scan_block(statement.orelse, autocommit=autocommit)
                continue
            call = _statement_call(statement)
            if call is not None:
                self._scan_call(call, autocommit=autocommit)

    def _scan_call(self, call: ast.Call, *, autocommit: bool) -> None:
        operation = _op_method(call)
        if operation is None:
            return
        line = getattr(call, "lineno", 1)

        if operation == "create_table":
            table = _string_argument(call, 0, "table_name")
            if table:
                self.created_tables.add(table)
            return

        if operation in _DESTRUCTIVE_OPS:
            self._issue(
                "destructive-change",
                MigrationSeverity.ERROR,
                line,
                f"op.{operation}() is destructive in upgrade(); "
                "use expand/contract or an explicit waiver",
            )
            return

        if operation == "create_index":
            table = _string_argument(call, 1, "table_name")
            if table and table in self.created_tables:
                return
            if _keyword_bool(call, "postgresql_concurrently") is not True:
                self._issue(
                    "blocking-index",
                    MigrationSeverity.ERROR,
                    line,
                    "index on an existing table must use postgresql_concurrently=True",
                )
            elif not autocommit:
                self._issue(
                    "concurrent-index-transaction",
                    MigrationSeverity.ERROR,
                    line,
                    "CREATE INDEX CONCURRENTLY must run inside autocommit_block()",
                )
            return

        if operation in {"create_check_constraint", "create_foreign_key"}:
            table = _string_argument(call, 1, "table_name")
            if operation == "create_foreign_key":
                table = _string_argument(call, 1, "source_table") or table
            if table and table in self.created_tables:
                return
            if _keyword_bool(call, "postgresql_not_valid") is not True:
                self._issue(
                    "immediate-constraint-validation",
                    MigrationSeverity.ERROR,
                    line,
                    "constraint on an existing table should be added NOT VALID "
                    "and validated separately",
                )
            return

        if operation == "add_column":
            table = _string_argument(call, 0, "table_name")
            if table and table in self.created_tables:
                return
            column_call = _call_argument(call, 1, "column")
            if column_call is not None and _call_method(column_call) == "Column":
                nullable = _keyword_value(column_call, "nullable")
                server_default = _keyword_value(column_call, "server_default")
                non_null = isinstance(nullable, ast.Constant) and nullable.value is False
                if non_null and server_default is None:
                    self._issue(
                        "non-null-column-without-backfill",
                        MigrationSeverity.ERROR,
                        line,
                        "non-null column on an existing table requires an "
                        "expand/backfill/enforce sequence",
                    )
            return

        if operation == "alter_column":
            if _keyword_value(call, "type_") is not None:
                self._issue(
                    "column-type-rewrite",
                    MigrationSeverity.ERROR,
                    line,
                    "column type changes may rewrite/lock the table; use a staged "
                    "expand/backfill/switch plan",
                )
            nullable = _keyword_value(call, "nullable")
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                self._issue(
                    "set-not-null",
                    MigrationSeverity.WARNING,
                    line,
                    "SET NOT NULL scans existing rows; validate data and budget "
                    "the lock before deployment",
                )
            return

        if operation == "execute":
            text = ast.get_source_segment(self.source, call) or ""
            upper = text.upper()
            if "DROP TABLE" in upper or "DROP COLUMN" in upper or "DROP TYPE" in upper:
                self._issue(
                    "destructive-sql",
                    MigrationSeverity.ERROR,
                    line,
                    "raw SQL contains a destructive DROP operation",
                )
            else:
                self._issue(
                    "raw-sql-review",
                    MigrationSeverity.WARNING,
                    line,
                    "op.execute() requires manual lock/rewrite/idempotency review",
                )

    def _issue(
        self,
        code: str,
        severity: MigrationSeverity,
        line: int,
        message: str,
    ) -> None:
        self.issues.append(MigrationSafetyIssue(code, severity, line, message))


def _extract_waivers(tree: ast.Module) -> frozenset[str]:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        has_waiver_target = any(
            isinstance(target, ast.Name) and target.id == "migration_safety_allow"
            for target in targets
        )
        if not has_waiver_target:
            continue
        value = node.value
        if not isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            raise ValueError(
                "migration_safety_allow must be a literal set/list/tuple of strings"
            )
        items: set[str] = set()
        for element in value.elts:
            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                raise ValueError("migration_safety_allow entries must be literal strings")
            items.add(element.value)
        return frozenset(items)
    return frozenset()


def _statement_call(statement: ast.stmt) -> ast.Call | None:
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        return statement.value
    return None


def _op_method(call: ast.Call) -> str | None:
    function = call.func
    if (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "op"
    ):
        return function.attr
    return None


def _call_method(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return None


def _call_argument(call: ast.Call, position: int, keyword: str) -> ast.Call | None:
    value: ast.AST | None
    if len(call.args) > position:
        value = call.args[position]
    else:
        value = _keyword_value(call, keyword)
    return value if isinstance(value, ast.Call) else None


def _string_argument(call: ast.Call, position: int, keyword: str) -> str | None:
    value: ast.AST | None
    if len(call.args) > position:
        value = call.args[position]
    else:
        value = _keyword_value(call, keyword)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _keyword_value(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _keyword_bool(call: ast.Call, name: str) -> bool | None:
    value = _keyword_value(call, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, bool):
        return value.value
    return None


def _is_autocommit_context(expression: ast.expr) -> bool:
    if not isinstance(expression, ast.Call):
        return False
    function = expression.func
    return isinstance(function, ast.Attribute) and function.attr == "autocommit_block"


__all__ = [
    "MigrationSafetyError",
    "MigrationSafetyIssue",
    "MigrationSafetyReport",
    "MigrationSeverity",
    "assert_migration_file_safe",
    "inspect_migration_file",
    "inspect_migration_source",
]
