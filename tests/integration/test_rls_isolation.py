from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import RequestContext, request_context
from prodkit_storage.database.runtime import SyncDatabase

pytestmark = pytest.mark.integration

_ROLE = "prodkit_ci_rls_runtime"
_TABLE = "storage_ci_rls_documents"
_TENANT_A = UUID("00000000-0000-0000-0000-0000000000a1")
_TENANT_B = UUID("00000000-0000-0000-0000-0000000000b2")


def _admin_database() -> SyncDatabase:
    return SyncDatabase(StorageSettings(environment="test"))


def _rls_database() -> SyncDatabase:
    return SyncDatabase(
        StorageSettings(
            environment="test",
            tenant_rls_enabled=True,
            tenant_required=True,
        )
    )


def _bootstrap() -> None:
    database = _admin_database()
    try:
        with database.write_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS public.{_TABLE} CASCADE")
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {_ROLE}")
            connection.exec_driver_sql(f"CREATE ROLE {_ROLE} NOLOGIN NOBYPASSRLS NOSUPERUSER")
            connection.exec_driver_sql(
                f"CREATE TABLE public.{_TABLE} ("
                "id bigint PRIMARY KEY, "
                "tenant_id uuid NOT NULL, "
                "body text NOT NULL)"
            )
            connection.exec_driver_sql(f"ALTER TABLE public.{_TABLE} ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"ALTER TABLE public.{_TABLE} FORCE ROW LEVEL SECURITY")
            connection.exec_driver_sql(
                f"CREATE POLICY tenant_isolation ON public.{_TABLE} TO {_ROLE} "
                "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                "WITH CHECK ("
                "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {_ROLE}")
            connection.exec_driver_sql(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.{_TABLE} TO {_ROLE}"
            )
    finally:
        database.dispose()


def _cleanup() -> None:
    database = _admin_database()
    try:
        with database.write_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS public.{_TABLE} CASCADE")
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {_ROLE}")
    finally:
        database.dispose()


def _insert(database: SyncDatabase, tenant: UUID, row_tenant: UUID, row_id: int) -> None:
    with request_context(RequestContext(tenant_id=tenant)):
        with database.transaction() as session:
            session.execute(text(f"SET LOCAL ROLE {_ROLE}"))
            session.execute(
                text(
                    f"INSERT INTO public.{_TABLE} (id, tenant_id, body) "
                    "VALUES (:id, :tenant_id, :body)"
                ),
                {"id": row_id, "tenant_id": row_tenant, "body": f"row-{row_id}"},
            )


def _visible_ids(database: SyncDatabase, tenant: UUID) -> list[int]:
    with request_context(RequestContext(tenant_id=tenant)):
        with database.read_transaction() as session:
            session.execute(text(f"SET LOCAL ROLE {_ROLE}"))
            rows = session.execute(
                text(f"SELECT id FROM public.{_TABLE} ORDER BY id")
            ).scalars()
            return [int(value) for value in rows]


def test_rls_prevents_cross_tenant_reads_and_writes() -> None:
    _bootstrap()
    database = _rls_database()
    try:
        _insert(database, _TENANT_A, _TENANT_A, 1)
        _insert(database, _TENANT_B, _TENANT_B, 2)

        assert _visible_ids(database, _TENANT_A) == [1]
        assert _visible_ids(database, _TENANT_B) == [2]

        with pytest.raises(DBAPIError):
            _insert(database, _TENANT_A, _TENANT_B, 3)

        assert _visible_ids(database, _TENANT_A) == [1]
        assert _visible_ids(database, _TENANT_B) == [2]
    finally:
        database.dispose()
        _cleanup()
