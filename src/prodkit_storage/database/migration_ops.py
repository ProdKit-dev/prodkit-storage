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

from collections.abc import Mapping, Sequence
from typing import Any

from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.sql.elements import ColumnElement, TextClause

from prodkit_storage.database.vector import (
    HNSWIndexOptions,
    IVFFlatIndexOptions,
    VectorDistance,
    VectorIndexMethod,
    VectorKind,
    vector_operator_class,
)

IndexColumn = str | TextClause | ColumnElement[Any]
IndexPredicate = str | TextClause | ColumnElement[bool]
IndexStorageValue = str | int | float


def create_index_concurrently(
    operations: Operations,
    name: str,
    table_name: str,
    columns: Sequence[IndexColumn],
    *,
    schema: str | None = None,
    unique: bool = False,
    using: str | None = None,
    opclasses: Mapping[str, str] | None = None,
    storage_parameters: Mapping[str, IndexStorageValue] | None = None,
    where: IndexPredicate | None = None,
    include: Sequence[str] = (),
) -> None:
    """Create a PostgreSQL index concurrently with advanced index options.

    The original column-only call remains fully compatible. PostgreSQL access
    method, operator classes, storage parameters, partial predicates, and
    included columns are additive options for GIN/vector/specialized indexes.

    Put this operation in a dedicated migration revision whenever possible:
    entering ``autocommit_block()`` commits any transaction that precedes it.
    """

    if not columns:
        raise ValueError("at least one index column is required")

    dialect_options: dict[str, Any] = {"postgresql_concurrently": True}
    if using is not None:
        dialect_options["postgresql_using"] = _sql_identifier(using, "index access method")
    if opclasses:
        dialect_options["postgresql_ops"] = {
            _sql_identifier(column, "operator-class column"): _qualified_identifier(
                operator_class,
                "operator class",
            )
            for column, operator_class in opclasses.items()
        }
    if storage_parameters:
        dialect_options["postgresql_with"] = {
            _sql_identifier(key, "index storage parameter"): value
            for key, value in storage_parameters.items()
        }
    if where is not None:
        dialect_options["postgresql_where"] = text(where) if isinstance(where, str) else where
    if include:
        dialect_options["postgresql_include"] = [
            _sql_identifier(column, "included column") for column in include
        ]

    with operations.get_context().autocommit_block():
        operations.create_index(
            operations.f(name),
            table_name,
            list(columns),
            schema=schema,
            unique=unique,
            **dialect_options,
        )


def create_tsvector_gin_index_concurrently(
    operations: Operations,
    name: str,
    table_name: str,
    column_name: str,
    *,
    schema: str | None = None,
    where: IndexPredicate | None = None,
    include: Sequence[str] = (),
) -> None:
    """Create a concurrent PostgreSQL GIN index for a ``tsvector`` column."""

    create_index_concurrently(
        operations,
        name,
        table_name,
        [_sql_identifier(column_name, "tsvector column")],
        schema=schema,
        using="gin",
        where=where,
        include=include,
    )


def create_vector_index_concurrently(
    operations: Operations,
    name: str,
    table_name: str,
    column_name: str,
    *,
    kind: VectorKind | str = VectorKind.VECTOR,
    distance: VectorDistance | str = VectorDistance.COSINE,
    method: VectorIndexMethod | str = VectorIndexMethod.HNSW,
    options: HNSWIndexOptions | IVFFlatIndexOptions | None = None,
    schema: str | None = None,
    where: IndexPredicate | None = None,
    include: Sequence[str] = (),
) -> None:
    """Create a concurrent HNSW or IVFFlat pgvector index.

    This helper never installs or upgrades the PostgreSQL ``vector`` extension.
    Deployment infrastructure must provision that capability first.
    """

    selected_method = VectorIndexMethod(method)
    selected_kind = VectorKind(kind)
    selected_distance = VectorDistance(distance)
    if options is not None:
        if selected_method is VectorIndexMethod.HNSW and not isinstance(options, HNSWIndexOptions):
            raise TypeError("HNSW indexes require HNSWIndexOptions")
        if selected_method is VectorIndexMethod.IVFFLAT and not isinstance(
            options, IVFFlatIndexOptions
        ):
            raise TypeError("IVFFlat indexes require IVFFlatIndexOptions")
    storage_parameters = {} if options is None else options.storage_parameters()
    column = _sql_identifier(column_name, "vector column")
    create_index_concurrently(
        operations,
        name,
        table_name,
        [column],
        schema=schema,
        using=selected_method.value,
        opclasses={
            column: vector_operator_class(
                selected_kind,
                selected_distance,
                method=selected_method,
            )
        },
        storage_parameters=storage_parameters,
        where=where,
        include=include,
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


def _sql_identifier(value: str, kind: str) -> str:
    normalized = value.strip()
    if not normalized or any(
        not (character.isalnum() or character == "_") for character in normalized
    ):
        raise ValueError(f"{kind} must contain only letters, digits, and underscores")
    return normalized


def _qualified_identifier(value: str, kind: str) -> str:
    normalized = value.strip()
    parts = normalized.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError(f"{kind} must be a PostgreSQL identifier")
    for part in parts:
        _sql_identifier(part, kind)
    return normalized


__all__ = [
    "HNSWIndexOptions",
    "IVFFlatIndexOptions",
    "IndexColumn",
    "IndexPredicate",
    "VectorDistance",
    "VectorIndexMethod",
    "VectorKind",
    "add_check_constraint_not_valid",
    "add_foreign_key_not_valid",
    "create_index_concurrently",
    "create_tsvector_gin_index_concurrently",
    "create_vector_index_concurrently",
    "enforce_not_null",
    "validate_constraint",
]
