"""Stable PostgreSQL inspection snapshots."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import Connection, Engine, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@contextmanager
def repeatable_read_sync(
    engine: Engine,
    *,
    read_only: bool = True,
) -> Iterator[Connection]:
    """Open a sync ``REPEATABLE READ`` transaction on the selected engine.

    The caller chooses primary vs replica by choosing the engine. The helper
    does not retry, route, commit writes implicitly, or alter global engine
    isolation configuration.
    """

    with engine.connect() as raw_connection:
        connection = raw_connection.execution_options(isolation_level="REPEATABLE READ")
        with connection.begin():
            if read_only:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            yield connection


@asynccontextmanager
async def repeatable_read_async(
    engine: AsyncEngine,
    *,
    read_only: bool = True,
) -> AsyncIterator[AsyncConnection]:
    """Open an async ``REPEATABLE READ`` transaction on the selected engine."""

    async with engine.connect() as raw_connection:
        connection = await raw_connection.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            if read_only:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
            yield connection


__all__ = ["repeatable_read_async", "repeatable_read_sync"]
