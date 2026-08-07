"""FastAPI dependencies that preserve explicit storage transaction boundaries."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable

from prodkit_storage.database.runtime import AsyncDatabase
from prodkit_storage.database.sessions import AsyncReadSession, AsyncWriteSession

DatabaseDependency = Callable[[], Awaitable[AsyncDatabase]]
WriteSessionDependency = Callable[[], AsyncGenerator[AsyncWriteSession, None]]
ReadSessionDependency = Callable[[], AsyncGenerator[AsyncReadSession, None]]


def create_database_dependency(database: AsyncDatabase) -> DatabaseDependency:
    async def get_database() -> AsyncDatabase:
        return database

    return get_database


def create_write_session_dependency(database: AsyncDatabase) -> WriteSessionDependency:
    async def get_write_session() -> AsyncGenerator[AsyncWriteSession, None]:
        async with database.transaction() as session:
            yield session

    return get_write_session


def create_read_session_dependency(database: AsyncDatabase) -> ReadSessionDependency:
    async def get_read_session() -> AsyncGenerator[AsyncReadSession, None]:
        async with database.read_transaction() as session:
            yield session

    return get_read_session


__all__ = [
    "DatabaseDependency",
    "ReadSessionDependency",
    "WriteSessionDependency",
    "create_database_dependency",
    "create_read_session_dependency",
    "create_write_session_dependency",
]
