"""Read-only PostgreSQL index inspection."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class PostgreSQLIndexState:
    schema: str
    table: str
    name: str
    access_method: str
    unique: bool
    valid: bool
    ready: bool
    predicate: str | None
    definition: str


_INDEX_QUERY = text(
    """
    SELECT
        ns.nspname AS schema_name,
        table_rel.relname AS table_name,
        index_rel.relname AS index_name,
        am.amname AS access_method,
        idx.indisunique AS is_unique,
        idx.indisvalid AS is_valid,
        idx.indisready AS is_ready,
        pg_get_expr(idx.indpred, idx.indrelid) AS predicate,
        pg_get_indexdef(idx.indexrelid) AS definition
    FROM pg_index AS idx
    JOIN pg_class AS index_rel ON index_rel.oid = idx.indexrelid
    JOIN pg_class AS table_rel ON table_rel.oid = idx.indrelid
    JOIN pg_namespace AS ns ON ns.oid = table_rel.relnamespace
    JOIN pg_am AS am ON am.oid = index_rel.relam
    WHERE ns.nspname = :schema_name
      AND table_rel.relname = :table_name
    ORDER BY index_rel.relname
    """
)


def inspect_indexes_sync(
    connection: Connection,
    table_name: str,
    *,
    schema: str = "public",
) -> tuple[PostgreSQLIndexState, ...]:
    """Inspect PostgreSQL indexes for one table without mutating schema."""

    params = _inspection_params(table_name, schema)
    rows = connection.execute(_INDEX_QUERY, params).mappings()
    return tuple(_index_state(row) for row in rows)


async def inspect_indexes_async(
    connection: AsyncConnection,
    table_name: str,
    *,
    schema: str = "public",
) -> tuple[PostgreSQLIndexState, ...]:
    """Async index inspection equivalent to :func:`inspect_indexes_sync`."""

    params = _inspection_params(table_name, schema)
    result = await connection.execute(_INDEX_QUERY, params)
    return tuple(_index_state(row) for row in result.mappings())


def require_valid_indexes(
    indexes: tuple[PostgreSQLIndexState, ...],
    *names: str,
) -> None:
    """Fail when named indexes are missing or not both valid and ready."""

    expected = tuple(dict.fromkeys(_identifier(name, "index") for name in names))
    by_name = {index.name: index for index in indexes}
    missing = tuple(name for name in expected if name not in by_name)
    unusable = tuple(
        name
        for name in expected
        if name in by_name and not (by_name[name].valid and by_name[name].ready)
    )
    if missing or unusable:
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unusable:
            details.append(f"unusable={','.join(unusable)}")
        raise RuntimeError("required PostgreSQL indexes unavailable: " + "; ".join(details))


def _inspection_params(table_name: str, schema: str) -> dict[str, str]:
    return {
        "table_name": _identifier(table_name, "table"),
        "schema_name": _identifier(schema, "schema"),
    }


def _index_state(row: object) -> PostgreSQLIndexState:
    mapping = getattr(row, "_mapping", row)
    return PostgreSQLIndexState(
        schema=str(mapping["schema_name"]),
        table=str(mapping["table_name"]),
        name=str(mapping["index_name"]),
        access_method=str(mapping["access_method"]),
        unique=bool(mapping["is_unique"]),
        valid=bool(mapping["is_valid"]),
        ready=bool(mapping["is_ready"]),
        predicate=None if mapping["predicate"] is None else str(mapping["predicate"]),
        definition=str(mapping["definition"]),
    )


def _identifier(value: str, kind: str) -> str:
    normalized = value.strip()
    if not normalized or "\x00" in normalized:
        raise ValueError(f"{kind} name must be non-empty and must not contain NUL bytes")
    return normalized


__all__ = [
    "PostgreSQLIndexState",
    "inspect_indexes_async",
    "inspect_indexes_sync",
    "require_valid_indexes",
]
