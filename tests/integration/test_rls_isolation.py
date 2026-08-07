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
_TENANT_A = UUID("00000000-0000-0000-0000-0000000000a1")
_TENANT_B = UUID("00000000-0000-0000-0000-0000000000b2")

_DROP_TABLE_SQL = "DROP TABLE IF EXISTS public.storage_ci_rls_documents CASCADE"
_DROP_ROLE_SQL = "DROP ROLE IF EXISTS prodkit_ci_rls_runtime"
_CREATE_ROLE_SQL = (
    "CREATE ROLE prodkit_ci_rls_runtime NOLOGIN NOBYPASSRLS NOSUPERUSER"
)
_CREATE_TABLE_SQL = (
    "CREATE TABLE public.storage_ci_rls_documents ("
    "id bigint PRIMARY KEY, "
    "tenant_id uuid NOT NULL, "
    "body text NOT NULL)"
)
_ENABLE_RLS_SQL = (
    "ALTER TABLE public.storage_ci_rls_documents ENABLE ROW LEVEL SECURITY"
)
_FORCE_RLS_SQL = (
    "ALTER TABLE public.storage_ci_rls_documents FORCE ROW LEVEL SECURITY"
)
_CREATE_POLICY_SQL = (
    "CREATE POLICY tenant_isolation ON public.storage_ci_rls_documents "
    "TO prodkit_ci_rls_runtime "
    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
    "WITH CHECK (tenant_id = "
    "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)
_GRANT_SCHEMA_SQL = "GRANT USAGE ON SCHEMA public TO prodkit_ci_rls_runtime"
_GRANT_TABLE_SQL = (
    "GRANT SELECT, INSERT, UPDATE, DELETE ON public.storage_ci_rls_documents "
    "TO prodkit_ci_rls_runtime"
)
_SET_ROLE_SQL = "SET LOCAL ROLE prodkit_ci_rls_runtime"
_INSERT_SQL = text(
    "INSERT INTO public.storage_ci_rls_documents (id, tenant_id, body) "
    "VALUES (:id, :tenant_id, :body)"
)
_SELECT_IDS_SQL = text("SELECT id FROM public.storage_ci_rls_documents ORDER BY id")


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
            for statement in (
                _DROP_TABLE_SQL,
                _DROP_ROLE_SQL,
                _CREATE_ROLE_SQL,
                _CREATE_TABLE_SQL,
                _ENABLE_RLS_SQL,
                _FORCE_RLS_SQL,
                _CREATE_POLICY_SQL,
                _GRANT_SCHEMA_SQL,
                _GRANT_TABLE_SQL,
            ):
                connection.exec_driver_sql(statement)
    finally:
        database.dispose()


def _cleanup() -> None:
    database = _admin_database()
    try:
        with database.write_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(_DROP_TABLE_SQL)
            connection.exec_driver_sql(_DROP_ROLE_SQL)
    finally:
        database.dispose()


def _insert(database: SyncDatabase, tenant: UUID, row_tenant: UUID, row_id: int) -> None:
    with request_context(RequestContext(tenant_id=tenant)):
        with database.transaction() as session:
            session.execute(text(_SET_ROLE_SQL))
            session.execute(
                _INSERT_SQL,
                {"id": row_id, "tenant_id": row_tenant, "body": f"row-{row_id}"},
            )


def _visible_ids(database: SyncDatabase, tenant: UUID) -> list[int]:
    with request_context(RequestContext(tenant_id=tenant)):
        with database.read_transaction() as session:
            session.execute(text(_SET_ROLE_SQL))
            rows = session.execute(_SELECT_IDS_SQL).scalars()
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
