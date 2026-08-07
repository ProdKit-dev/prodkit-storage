"""Alembic helpers for staged PostgreSQL schema changes.

These helpers make the preferred operational patterns easy to reuse while
leaving destructive contract operations explicit in each revision so the
migration safety linter can require a visible waiver.

A PostgreSQL concurrent-index operation requires Alembic's ``autocommit_block``.
Alembic commits the transaction preceding that block, so concurrent index work
should normally live in a dedicated revision rather than being mixed with other
schema mutations that callers expect to be atomic with it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic.operations import Operations
from sqlalchemy import text


def create_index_concurrently(
    operations: Operations,
    name: str,
    table_name: str,
    columns: Sequence[str],
    *,
    schema: str | None = None,
    unique: bool = False,
) -> None:
    """Create an index concurrently outside Alembic's normal transaction.

    Put this operation in a dedicated migration revision whenever possible:
    entering ``autocommit_block()`` commits any transaction that precedes it.
    """

    if not columns:
        raise ValueError("at least one index column is required")
    with operations.get_context().autocommit_block():
        operations.create_index(
            operations.f(name),
            table_name,
            list(columns),
            schema=schema,
            unique=unique,
            postgresql_concurrently=True,
        )


def add_check_constraint_not_valid(
    operations: Operations,
    name: str,
    table_name: str,
    condition: str,
    *,
    schema: str | None = None,
) -> None:
    """Add a PostgreSQL CHECK constraint without scanning existing rows."""

    if not condition.strip():
        raise ValueError("check constraint condition must not be empty")
    operations.create_check_constraint(
        operations.f(name),
        table_name,
        text(condition),
        schema=schema,
        postgresql_not_valid=True,
    )


def add_foreign_key_not_valid(
    operations: Operations,
    name: str,
    source_table: str,
    referent_table: str,
    local_columns: Sequence[str],
    remote_columns: Sequence[str],
    *,
    source_schema: str | None = None,
    referent_schema: str | None = None,
    ondelete: str | None = None,
    onupdate: str | None = None,
) -> None:
    """Add a PostgreSQL foreign key without immediately validating old rows."""

    if not local_columns or len(local_columns) != len(remote_columns):
        raise ValueError("foreign-key column lists must be non-empty and have equal length")
    operations.create_foreign_key(
        operations.f(name),
        source_table,
        referent_table,
        list(local_columns),
        list(remote_columns),
        source_schema=source_schema,
        referent_schema=referent_schema,
        ondelete=ondelete,
        onupdate=onupdate,
        postgresql_not_valid=True,
    )


def validate_constraint(
    operations: Operations,
    table_name: str,
    constraint_name: str,
    *,
    schema: str | None = None,
) -> None:
    """Validate an existing PostgreSQL constraint with safely quoted identifiers."""

    preparer = operations.get_context().dialect.identifier_preparer
    table = preparer.quote(table_name)
    if schema is not None:
        table = f"{preparer.quote_schema(schema)}.{table}"
    constraint = preparer.quote(str(operations.f(constraint_name)))
    operations.execute(text(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}"))


def enforce_not_null(
    operations: Operations,
    table_name: str,
    column_name: str,
    *,
    schema: str | None = None,
    check_name: str | None = None,
) -> None:
    """Enforce NOT NULL using a prevalidated CHECK to avoid a second table scan.

    Existing rows should already have been backfilled. PostgreSQL can use the
    validated temporary CHECK as proof when applying ``SET NOT NULL``.
    """

    name = check_name or f"ck_{table_name}_{column_name}_not_null"
    preparer = operations.get_context().dialect.identifier_preparer
    quoted_column = preparer.quote(column_name)
    add_check_constraint_not_valid(
        operations,
        name,
        table_name,
        f"{quoted_column} IS NOT NULL",
        schema=schema,
    )
    validate_constraint(operations, table_name, name, schema=schema)
    operations.alter_column(
        table_name,
        column_name,
        schema=schema,
        nullable=False,
    )
    operations.drop_constraint(
        operations.f(name),
        table_name,
        schema=schema,
        type_="check",
    )


__all__ = [
    "add_check_constraint_not_valid",
    "add_foreign_key_not_valid",
    "create_index_concurrently",
    "enforce_not_null",
    "validate_constraint",
]
