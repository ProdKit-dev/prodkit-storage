"""Safe helpers for tenant RLS migration code."""

from __future__ import annotations

import hashlib
import re

from alembic.operations import Operations

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SETTING = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_POSTGRES_IDENTIFIER_LIMIT = 63


def enable_tenant_rls(
    op: Operations,
    table: str,
    *,
    tenant_column: str = "tenant_id",
    setting: str = "app.tenant_id",
    schema: str | None = None,
    force: bool = True,
) -> None:
    table = _identifier(table)
    tenant_column = _identifier(tenant_column)
    qualified_table = _qualified_table(table, schema)
    policy = _policy_name(table)
    if _SETTING.fullmatch(setting) is None:
        raise ValueError(f"unsafe PostgreSQL setting name: {setting!r}")
    op.execute(f"ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY")
    if force:
        op.execute(f"ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f'''CREATE POLICY "{policy}" ON {qualified_table}
        USING ("{tenant_column}" = NULLIF(current_setting('{setting}', true), '')::uuid)
        WITH CHECK ("{tenant_column}" = NULLIF(current_setting('{setting}', true), '')::uuid)'''
    )


def disable_tenant_rls(
    op: Operations,
    table: str,
    *,
    schema: str | None = None,
) -> None:
    table = _identifier(table)
    qualified_table = _qualified_table(table, schema)
    policy = _policy_name(table)
    op.execute(f'DROP POLICY IF EXISTS "{policy}" ON {qualified_table}')
    op.execute(f"ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY")


def _qualified_table(table: str, schema: str | None) -> str:
    if schema is None:
        return f'"{table}"'
    return f'"{_identifier(schema)}"."{table}"'


def _policy_name(table: str) -> str:
    candidate = f"{table}_tenant_isolation"
    if len(candidate) <= _POSTGRES_IDENTIFIER_LIMIT:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:10]
    prefix_length = _POSTGRES_IDENTIFIER_LIMIT - len(digest) - 1
    return f"{candidate[:prefix_length]}_{digest}"


def _identifier(value: str) -> str:
    if len(value) > _POSTGRES_IDENTIFIER_LIMIT or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value
