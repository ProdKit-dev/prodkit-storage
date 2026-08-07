from __future__ import annotations

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.migration_ops import (
    add_check_constraint_not_valid,
    create_index_concurrently,
    enforce_not_null,
    validate_constraint,
)
from prodkit_storage.database.runtime import SyncDatabase

pytestmark = pytest.mark.integration

_TABLE = "storage_ci_migration_ops"
_INDEX = "ix_storage_ci_migration_ops_value"
_CHECK = "ck_storage_ci_migration_ops_positive"
_DROP_TABLE = "DROP TABLE IF EXISTS storage_ci_migration_ops"
_CREATE_TABLE = (
    "CREATE TABLE storage_ci_migration_ops ("
    "id integer PRIMARY KEY, value integer NULL)"
)
_INSERT_ROWS = (
    "INSERT INTO storage_ci_migration_ops (id, value) VALUES (1, 1), (2, 2)"
)


def test_concurrent_index_and_deferred_constraint_helpers() -> None:
    database = SyncDatabase(StorageSettings(environment="test"))
    try:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_TABLE)
            connection.exec_driver_sql(_CREATE_TABLE)
            connection.exec_driver_sql(_INSERT_ROWS)

        with database.write_engine.connect() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            with context.begin_transaction():
                create_index_concurrently(
                    operations,
                    _INDEX,
                    _TABLE,
                    ["value"],
                )

        with database.write_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = :table AND indexname = :index"
                ),
                {"table": _TABLE, "index": _INDEX},
            ) == 1

        with database.write_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            add_check_constraint_not_valid(
                operations,
                _CHECK,
                _TABLE,
                "value > 0",
            )

        with database.write_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = :name"
                ),
                {"name": _CHECK},
            ) is False

        with database.write_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            validate_constraint(operations, _TABLE, _CHECK)

        with database.write_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = :name"
                ),
                {"name": _CHECK},
            ) is True
    finally:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_TABLE)
        database.dispose()


def test_enforce_not_null_uses_validated_check_path() -> None:
    database = SyncDatabase(StorageSettings(environment="test"))
    try:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_TABLE)
            connection.exec_driver_sql(_CREATE_TABLE)
            connection.exec_driver_sql(_INSERT_ROWS)

        with database.write_engine.begin() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            enforce_not_null(operations, _TABLE, "value")

        with database.write_engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT attnotnull FROM pg_attribute "
                    "WHERE attrelid = to_regclass(:table) AND attname = 'value'"
                ),
                {"table": _TABLE},
            ) is True
    finally:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_TABLE)
        database.dispose()
