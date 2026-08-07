"""Runtime verification for PostgreSQL Row-Level Security deployments."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class RLSRoleStatus:
    role: str
    exists: bool
    superuser: bool
    bypass_rls: bool


@dataclass(frozen=True, slots=True)
class RLSTableStatus:
    table: str
    owner: str | None
    rls_enabled: bool
    force_rls: bool
    policy_count: int


@dataclass(frozen=True, slots=True)
class RLSVerificationReport:
    healthy: bool
    role: RLSRoleStatus
    tables: tuple[RLSTableStatus, ...]
    issues: tuple[str, ...]


_ROLE_SQL = text(
    """
    SELECT rolname, rolsuper, rolbypassrls
    FROM pg_roles
    WHERE rolname = :role
    """
)
_TABLE_SQL = text(
    """
    SELECT
      c.relname AS table_name,
      owner.rolname AS owner_name,
      c.relrowsecurity AS rls_enabled,
      c.relforcerowsecurity AS force_rls,
      COUNT(p.policyname) AS policy_count
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    JOIN pg_roles AS owner ON owner.oid = c.relowner
    LEFT JOIN pg_policies AS p
      ON p.schemaname = n.nspname AND p.tablename = c.relname
    WHERE n.nspname = :schema AND c.relname = ANY(CAST(:tables AS text[]))
    GROUP BY c.relname, owner.rolname, c.relrowsecurity, c.relforcerowsecurity
    ORDER BY c.relname
    """
)


def verify_rls_sync(
    session: Session,
    *,
    runtime_role: str,
    tables: Sequence[str],
    schema: str = "public",
    require_force_rls: bool = False,
) -> RLSVerificationReport:
    _validate_inputs(runtime_role, tables, schema)
    role_row = session.execute(_ROLE_SQL, {"role": runtime_role}).mappings().one_or_none()
    table_rows = session.execute(
        _TABLE_SQL, {"schema": schema, "tables": list(tables)}
    ).mappings().all()
    return _build_report(
        runtime_role,
        tables,
        role_row,
        table_rows,
        require_force_rls=require_force_rls,
    )


async def verify_rls_async(
    session: AsyncSession,
    *,
    runtime_role: str,
    tables: Sequence[str],
    schema: str = "public",
    require_force_rls: bool = False,
) -> RLSVerificationReport:
    _validate_inputs(runtime_role, tables, schema)
    role_result = await session.execute(_ROLE_SQL, {"role": runtime_role})
    role_row = role_result.mappings().one_or_none()
    table_result = await session.execute(
        _TABLE_SQL, {"schema": schema, "tables": list(tables)}
    )
    table_rows = table_result.mappings().all()
    return _build_report(
        runtime_role,
        tables,
        role_row,
        table_rows,
        require_force_rls=require_force_rls,
    )


def _build_report(
    runtime_role: str,
    requested_tables: Sequence[str],
    role_row: Any,
    table_rows: Sequence[Any],
    *,
    require_force_rls: bool,
) -> RLSVerificationReport:
    role = RLSRoleStatus(
        role=runtime_role,
        exists=role_row is not None,
        superuser=bool(role_row["rolsuper"]) if role_row is not None else False,
        bypass_rls=bool(role_row["rolbypassrls"]) if role_row is not None else False,
    )
    table_statuses = tuple(
        RLSTableStatus(
            table=str(row["table_name"]),
            owner=str(row["owner_name"]) if row["owner_name"] is not None else None,
            rls_enabled=bool(row["rls_enabled"]),
            force_rls=bool(row["force_rls"]),
            policy_count=int(row["policy_count"]),
        )
        for row in table_rows
    )
    issues: list[str] = []
    if not role.exists:
        issues.append(f"runtime role {runtime_role!r} does not exist")
    if role.superuser:
        issues.append("runtime role is a superuser")
    if role.bypass_rls:
        issues.append("runtime role has BYPASSRLS")
    found = {table.table for table in table_statuses}
    for missing in sorted(set(requested_tables) - found):
        issues.append(f"table {missing!r} was not found")
    for table in table_statuses:
        if table.owner == runtime_role:
            issues.append(f"runtime role owns RLS table {table.table!r}")
        if not table.rls_enabled:
            issues.append(f"RLS is not enabled on table {table.table!r}")
        if require_force_rls and not table.force_rls:
            issues.append(f"FORCE ROW LEVEL SECURITY is not enabled on {table.table!r}")
        if table.policy_count == 0:
            issues.append(f"table {table.table!r} has no RLS policies")
    return RLSVerificationReport(not issues, role, table_statuses, tuple(issues))


def _validate_inputs(runtime_role: str, tables: Sequence[str], schema: str) -> None:
    _identifier(runtime_role)
    _identifier(schema)
    if not tables:
        raise ValueError("at least one table is required")
    for table in tables:
        _identifier(table)


def _identifier(value: str) -> str:
    if re.fullmatch(r"[a-z_][a-z0-9_]*", value) is None:
        raise ValueError(f"invalid PostgreSQL identifier: {value!r}")
    return value


__all__ = [
    "RLSRoleStatus",
    "RLSTableStatus",
    "RLSVerificationReport",
    "verify_rls_async",
    "verify_rls_sync",
]
