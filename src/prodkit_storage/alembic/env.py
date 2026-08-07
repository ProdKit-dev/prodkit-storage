"""Alembic environment supporting psycopg and asyncpg URLs."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.base import Base
from prodkit_storage.models import AuditEvent, OutboxEvent  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = StorageSettings()
for model_module in settings.alembic_model_module_names:
    importlib.import_module(model_module)
target_metadata = Base.metadata
_POSTGIS_RELATIONS = {
    "spatial_ref_sys",
    "geometry_columns",
    "geography_columns",
    "raster_columns",
    "raster_overviews",
}


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    del compare_to
    if not reflected:
        return True
    if type_ not in {"table", "view"}:
        return True
    schema = getattr(object_, "schema", None)
    if schema not in {None, settings.database_schema}:
        return False
    if name == "storage_alembic_version":
        return False
    return name not in _POSTGIS_RELATIONS


def _url() -> str:
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    return configured or settings.sync_url.render_as_string(hide_password=False)


def _configure(connection: Connection | None, *, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        version_table="storage_alembic_version",
        version_table_schema=settings.database_schema,
        transaction_per_migration=True,
        render_as_batch=False,
        dialect_opts={"paramstyle": "named"},
        literal_binds=connection is None,
        include_object=_include_object,
    )


def _apply_migration_session_settings(execute: Callable[[str], Any]) -> None:
    if settings.migration_owner_role is not None:
        execute(f'SET ROLE "{settings.migration_owner_role}"')
    execute(f'SET search_path TO "{settings.database_schema}", public')


def run_migrations_offline() -> None:
    _configure(None, url=_url())
    migration_context = context.get_context()
    with context.begin_transaction():
        _apply_migration_session_settings(migration_context.execute)
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    connection.dialect.default_schema_name = settings.database_schema
    _configure(connection)
    with context.begin_transaction():
        _apply_migration_session_settings(connection.exec_driver_sql)
        context.run_migrations()


def run_sync_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run_sync_migrations(connection)
    engine.dispose()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    driver = make_url(_url()).get_driver_name()
    if driver in {"asyncpg", "psycopg_async"}:
        asyncio.run(run_async_migrations())
    else:
        run_sync_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
