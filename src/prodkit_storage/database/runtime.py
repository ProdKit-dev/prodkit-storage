"""Sync and async PostgreSQL engine/session lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.observability import install_query_observer
from prodkit_storage.database.tenant import StorageSession


class SyncDatabase:
    """Owns sync write/read engines and session factories.

    Read replicas are selected explicitly via :meth:`read_session`; write
    transactions never silently switch connections.
    """

    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.write_engine = _create_sync_engine(settings, readonly=False)
        self.read_engine = (
            _create_sync_engine(settings, readonly=True)
            if settings.sync_read_url is not None
            else self.write_engine
        )
        self.write_session_factory = sessionmaker(
            bind=self.write_engine,
            class_=StorageSession,
            autoflush=False,
            expire_on_commit=False,
            info={"storage_settings": settings, "read_only": False},
        )
        self.read_session_factory = sessionmaker(
            bind=self.read_engine,
            class_=StorageSession,
            autoflush=False,
            expire_on_commit=False,
            info={"storage_settings": settings, "read_only": True},
        )
        install_query_observer(self.write_engine, settings)
        if self.read_engine is not self.write_engine:
            install_query_observer(self.read_engine, settings)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.write_session_factory() as session:
            yield session

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        with self.read_session_factory() as session:
            yield session

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.write_session_factory.begin() as session:
            yield session

    @contextmanager
    def read_transaction(self) -> Iterator[Session]:
        with self.read_session_factory() as session, session.begin():
            yield session

    def dispose(self) -> None:
        if self.read_engine is not self.write_engine:
            self.read_engine.dispose()
        self.write_engine.dispose()


class AsyncDatabase:
    """Owns async write/read engines and async session factories."""

    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.write_engine = _create_async_engine(settings, readonly=False)
        self.read_engine = (
            _create_async_engine(settings, readonly=True)
            if settings.async_read_url is not None
            else self.write_engine
        )
        self.write_session_factory = async_sessionmaker(
            bind=self.write_engine,
            class_=AsyncSession,
            sync_session_class=StorageSession,
            autoflush=False,
            expire_on_commit=False,
            info={"storage_settings": settings, "read_only": False},
        )
        self.read_session_factory = async_sessionmaker(
            bind=self.read_engine,
            class_=AsyncSession,
            sync_session_class=StorageSession,
            autoflush=False,
            expire_on_commit=False,
            info={"storage_settings": settings, "read_only": True},
        )
        install_query_observer(self.write_engine.sync_engine, settings)
        if self.read_engine is not self.write_engine:
            install_query_observer(self.read_engine.sync_engine, settings)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.write_session_factory() as session:
            yield session

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        async with self.read_session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.write_session_factory.begin() as session:
            yield session

    @asynccontextmanager
    async def read_transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.read_session_factory() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        if self.read_engine is not self.write_engine:
            await self.read_engine.dispose()
        await self.write_engine.dispose()


def _postgres_options(settings: StorageSettings, *, readonly: bool) -> str:
    options = [
        f"-c statement_timeout={settings.statement_timeout_ms}",
        f"-c lock_timeout={settings.lock_timeout_ms}",
        f"-c idle_in_transaction_session_timeout={settings.idle_in_transaction_timeout_ms}",
        f"-c search_path={settings.database_schema},public",
    ]
    if readonly:
        options.append("-c default_transaction_read_only=on")
    return " ".join(options)


def _create_sync_engine(settings: StorageSettings, *, readonly: bool) -> Engine:
    url = (
        settings.sync_read_url
        if readonly and settings.sync_read_url is not None
        else settings.sync_url
    )
    return create_engine(
        url,
        echo=settings.echo_sql,
        pool_pre_ping=settings.pool_pre_ping,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        isolation_level=settings.isolation_level,
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "application_name": settings.application_name + ("-read" if readonly else "-write"),
            "options": _postgres_options(settings, readonly=readonly),
        },
    )


def _create_async_engine(settings: StorageSettings, *, readonly: bool) -> AsyncEngine:
    url = (
        settings.async_read_url
        if readonly and settings.async_read_url is not None
        else settings.async_url
    )
    server_settings = {
        "application_name": settings.application_name
        + ("-async-read" if readonly else "-async-write"),
        "statement_timeout": str(settings.statement_timeout_ms),
        "lock_timeout": str(settings.lock_timeout_ms),
        "idle_in_transaction_session_timeout": str(settings.idle_in_transaction_timeout_ms),
        "search_path": f"{settings.database_schema},public",
    }
    if readonly:
        server_settings["default_transaction_read_only"] = "on"
    return create_async_engine(
        url,
        echo=settings.echo_sql,
        pool_pre_ping=settings.pool_pre_ping,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        isolation_level=settings.isolation_level,
        connect_args={
            "timeout": settings.connect_timeout_seconds,
            "command_timeout": settings.command_timeout_seconds,
            "server_settings": server_settings,
        },
    )
