"""Explicit runtime compatibility checks for Alembic schema revisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Column, MetaData, Select, String, Table, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

STORAGE_SCHEMA_COMPATIBILITY_VERSION = 1
STORAGE_SCHEMA_HEAD = "20260807_0002"
STORAGE_ALEMBIC_VERSION_TABLE = "storage_alembic_version"


class SchemaRevisionState(StrEnum):
    CURRENT = "current"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNVERSIONED = "unversioned"
    MULTIPLE_HEADS = "multiple_heads"


@dataclass(frozen=True, slots=True)
class SchemaCompatibilityPolicy:
    expected_revision: str = STORAGE_SCHEMA_HEAD
    compatible_revisions: frozenset[str] = frozenset({STORAGE_SCHEMA_HEAD})
    compatibility_version: int = STORAGE_SCHEMA_COMPATIBILITY_VERSION

    def __post_init__(self) -> None:
        if not self.expected_revision.strip():
            raise ValueError("expected_revision must not be empty")
        if self.expected_revision not in self.compatible_revisions:
            raise ValueError("compatible_revisions must include expected_revision")
        if self.compatibility_version < 1:
            raise ValueError("compatibility_version must be positive")


@dataclass(frozen=True, slots=True)
class SchemaCompatibilityReport:
    state: SchemaRevisionState
    revisions: tuple[str, ...]
    expected_revision: str
    compatibility_version: int

    @property
    def compatible(self) -> bool:
        return self.state in {SchemaRevisionState.CURRENT, SchemaRevisionState.COMPATIBLE}


class SchemaCompatibilityError(RuntimeError):
    def __init__(self, report: SchemaCompatibilityReport) -> None:
        self.report = report
        revisions = ", ".join(report.revisions) or "<none>"
        super().__init__(
            "database schema is not compatible with this storage runtime: "
            f"state={report.state}, current={revisions}, expected={report.expected_revision}"
        )


DEFAULT_SCHEMA_POLICY = SchemaCompatibilityPolicy()
_VERSION_TABLE_EXISTS_SQL = text(
    """
    SELECT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_class AS c
      JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
      WHERE n.nspname = :schema
        AND c.relname = :table
        AND c.relkind IN ('r', 'p')
    )
    """
)


def evaluate_schema_revisions(
    revisions: tuple[str, ...],
    *,
    policy: SchemaCompatibilityPolicy = DEFAULT_SCHEMA_POLICY,
) -> SchemaCompatibilityReport:
    normalized = tuple(dict.fromkeys(item.strip() for item in revisions if item.strip()))
    if not normalized:
        state = SchemaRevisionState.UNVERSIONED
    elif len(normalized) != 1:
        state = SchemaRevisionState.MULTIPLE_HEADS
    elif normalized[0] == policy.expected_revision:
        state = SchemaRevisionState.CURRENT
    elif normalized[0] in policy.compatible_revisions:
        state = SchemaRevisionState.COMPATIBLE
    else:
        state = SchemaRevisionState.INCOMPATIBLE
    return SchemaCompatibilityReport(
        state=state,
        revisions=normalized,
        expected_revision=policy.expected_revision,
        compatibility_version=policy.compatibility_version,
    )


def _version_statement(schema: str) -> Select[tuple[str]]:
    metadata = MetaData()
    version_table = Table(
        STORAGE_ALEMBIC_VERSION_TABLE,
        metadata,
        Column("version_num", String(32), nullable=False),
        schema=schema,
    )
    return select(version_table.c.version_num).order_by(version_table.c.version_num)


def check_schema_compatibility_sync(
    session: Session,
    *,
    policy: SchemaCompatibilityPolicy = DEFAULT_SCHEMA_POLICY,
    schema: str = "public",
) -> SchemaCompatibilityReport:
    exists = session.scalar(
        _VERSION_TABLE_EXISTS_SQL,
        {"schema": schema, "table": STORAGE_ALEMBIC_VERSION_TABLE},
    )
    revisions: tuple[str, ...] = ()
    if bool(exists):
        revisions = tuple(
            str(value) for value in session.scalars(_version_statement(schema)).all()
        )
    return evaluate_schema_revisions(revisions, policy=policy)


async def check_schema_compatibility_async(
    session: AsyncSession,
    *,
    policy: SchemaCompatibilityPolicy = DEFAULT_SCHEMA_POLICY,
    schema: str = "public",
) -> SchemaCompatibilityReport:
    exists = await session.scalar(
        _VERSION_TABLE_EXISTS_SQL,
        {"schema": schema, "table": STORAGE_ALEMBIC_VERSION_TABLE},
    )
    revisions: tuple[str, ...] = ()
    if bool(exists):
        result = await session.scalars(_version_statement(schema))
        revisions = tuple(str(value) for value in result.all())
    return evaluate_schema_revisions(revisions, policy=policy)


def require_schema_compatible_sync(
    session: Session,
    *,
    policy: SchemaCompatibilityPolicy = DEFAULT_SCHEMA_POLICY,
    schema: str = "public",
) -> SchemaCompatibilityReport:
    report = check_schema_compatibility_sync(session, policy=policy, schema=schema)
    if not report.compatible:
        raise SchemaCompatibilityError(report)
    return report


async def require_schema_compatible_async(
    session: AsyncSession,
    *,
    policy: SchemaCompatibilityPolicy = DEFAULT_SCHEMA_POLICY,
    schema: str = "public",
) -> SchemaCompatibilityReport:
    report = await check_schema_compatibility_async(session, policy=policy, schema=schema)
    if not report.compatible:
        raise SchemaCompatibilityError(report)
    return report


__all__ = [
    "DEFAULT_SCHEMA_POLICY",
    "STORAGE_ALEMBIC_VERSION_TABLE",
    "STORAGE_SCHEMA_COMPATIBILITY_VERSION",
    "STORAGE_SCHEMA_HEAD",
    "SchemaCompatibilityError",
    "SchemaCompatibilityPolicy",
    "SchemaCompatibilityReport",
    "SchemaRevisionState",
    "check_schema_compatibility_async",
    "check_schema_compatibility_sync",
    "evaluate_schema_revisions",
    "require_schema_compatible_async",
    "require_schema_compatible_sync",
]
