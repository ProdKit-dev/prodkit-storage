from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import RequestContext, request_context
from prodkit_storage.database.locks import (
    acquire_advisory_xact_lock,
    acquire_advisory_xact_lock_async,
)
from prodkit_storage.database.runtime import _postgres_options
from prodkit_storage.database.tenant import _apply_context_after_begin
from prodkit_storage.database.transactions import (
    is_retryable_database_error,
    run_async_transaction,
    run_sync_transaction,
)
from prodkit_storage.database.uow import AsyncUnitOfWork, SyncUnitOfWork
from prodkit_storage.exceptions import LockNotAcquiredError, TenantContextError


class ScalarSession:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def scalar(self, statement: Any, parameters: Any) -> Any:
        del statement, parameters
        return self.values.pop(0)


class AsyncScalarSession(ScalarSession):
    async def scalar(self, statement: Any, parameters: Any) -> Any:
        return super().scalar(statement, parameters)


def test_postgres_advisory_lock_sync_and_async() -> None:
    session = ScalarSession([True, False, False])
    assert acquire_advisory_xact_lock(session, "invoice", "1")  # type: ignore[arg-type]
    assert not acquire_advisory_xact_lock(  # type: ignore[arg-type]
        session, "invoice", "2", required=False
    )
    with pytest.raises(LockNotAcquiredError):
        acquire_advisory_xact_lock(session, "invoice", "3")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_postgres_advisory_lock_async() -> None:
    session = AsyncScalarSession([True, False])
    assert await acquire_advisory_xact_lock_async(  # type: ignore[arg-type]
        session, "invoice", "1"
    )
    with pytest.raises(LockNotAcquiredError):
        await acquire_advisory_xact_lock_async(  # type: ignore[arg-type]
            session, "invoice", "2"
        )


class OrigError(Exception):
    sqlstate = "40001"


def retryable_error() -> OperationalError:
    return OperationalError("statement", {}, OrigError("serialization"))


def test_retryable_error_detection_and_sync_transaction_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert is_retryable_database_error(retryable_error())
    assert not is_retryable_database_error(RuntimeError("other"))
    monkeypatch.setattr("prodkit_storage.database.transactions.time.sleep", lambda delay: None)

    attempts = 0

    class Factory:
        @contextmanager
        def begin(self) -> Any:
            yield object()

    def operation(session: Any) -> str:
        nonlocal attempts
        del session
        attempts += 1
        if attempts == 1:
            raise retryable_error()
        return "done"

    assert run_sync_transaction(Factory(), operation) == "done"  # type: ignore[arg-type]
    assert attempts == 2


@pytest.mark.asyncio
async def test_async_transaction_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr("prodkit_storage.database.transactions.asyncio.sleep", no_sleep)
    attempts = 0

    class Factory:
        @asynccontextmanager
        async def begin(self) -> Any:
            yield object()

    async def operation(session: Any) -> str:
        nonlocal attempts
        del session
        attempts += 1
        if attempts == 1:
            raise retryable_error()
        return "done"

    assert await run_async_transaction(Factory(), operation) == "done"  # type: ignore[arg-type]
    assert attempts == 2


class FakeSyncUowSession:
    def __init__(self, *, fail_begin: bool = False) -> None:
        self.fail_begin = fail_begin
        self.calls: list[str] = []

    def begin(self) -> None:
        self.calls.append("begin")
        if self.fail_begin:
            raise RuntimeError("begin failed")

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


class FakeAsyncUowSession(FakeSyncUowSession):
    async def begin(self) -> None:
        super().begin()

    async def commit(self) -> None:
        super().commit()

    async def rollback(self) -> None:
        super().rollback()

    async def close(self) -> None:
        super().close()


def test_sync_unit_of_work_commit_and_implicit_rollback() -> None:
    committed = FakeSyncUowSession()
    with SyncUnitOfWork(lambda: committed) as uow:  # type: ignore[arg-type]
        uow.commit()
    assert committed.calls == ["begin", "commit", "close"]

    rolled_back = FakeSyncUowSession()
    with SyncUnitOfWork(lambda: rolled_back):  # type: ignore[arg-type]
        pass
    assert rolled_back.calls == ["begin", "rollback", "close"]

    failed = FakeSyncUowSession(fail_begin=True)
    with pytest.raises(RuntimeError, match="begin failed"):
        with SyncUnitOfWork(lambda: failed):  # type: ignore[arg-type]
            pass
    assert failed.calls == ["begin", "close"]


@pytest.mark.asyncio
async def test_async_unit_of_work_commit_and_rollback() -> None:
    committed = FakeAsyncUowSession()
    async with AsyncUnitOfWork(lambda: committed) as uow:  # type: ignore[arg-type]
        await uow.commit()
    assert committed.calls == ["begin", "commit", "close"]

    rolled_back = FakeAsyncUowSession()
    async with AsyncUnitOfWork(lambda: rolled_back):  # type: ignore[arg-type]
        await uow.rollback()
    assert rolled_back.calls == ["begin", "rollback", "close"]


class ContextConnection:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def execute(self, statement: Any, parameters: dict[str, str]) -> None:
        del statement
        self.calls.append(parameters)


class ContextSession:
    def __init__(self, settings: StorageSettings) -> None:
        self.info = {"storage_settings": settings}


def test_rls_context_is_transaction_local_and_can_fail_closed() -> None:
    settings = StorageSettings(
        tenant_rls_enabled=True,
        tenant_required=True,
        cursor_signing_secret=SecretStr("x" * 32),
    )
    session = ContextSession(settings)
    connection = ContextConnection()
    with pytest.raises(TenantContextError):
        _apply_context_after_begin(session, object(), connection)  # type: ignore[arg-type]

    tenant_id = UUID("19dd5df5-cf1f-461f-80fb-50b47be112f0")
    actor_id = UUID("dd10f1a1-297b-4512-9ca2-540322f99bd0")
    with request_context(
        RequestContext(tenant_id=tenant_id, actor_id=actor_id, request_id="req-1")
    ):
        _apply_context_after_begin(session, object(), connection)  # type: ignore[arg-type]
    assert connection.calls == [
        {"name": "app.tenant_id", "value": str(tenant_id)},
        {"name": "app.actor_id", "value": str(actor_id)},
        {"name": "app.request_id", "value": "req-1"},
    ]



def test_read_only_mode_is_applied_before_rls_context() -> None:
    settings = StorageSettings(tenant_rls_enabled=True)
    session = ContextSession(settings)
    session.info["read_only"] = True

    class OrderedConnection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str] | None]] = []

        def execute(
            self,
            statement: Any,
            parameters: dict[str, str] | None = None,
        ) -> None:
            self.calls.append((str(statement), parameters))

    connection = OrderedConnection()
    _apply_context_after_begin(session, object(), connection)  # type: ignore[arg-type]
    assert connection.calls[0] == ("SET TRANSACTION READ ONLY", None)
    assert connection.calls[1][1] == {"name": "app.tenant_id", "value": ""}


def test_postgres_connection_options_include_timeouts_and_readonly() -> None:
    settings = StorageSettings(cursor_signing_secret=SecretStr("x" * 32))
    options = _postgres_options(settings, readonly=True)
    assert "statement_timeout=30000" in options
    assert "lock_timeout=5000" in options
    assert "default_transaction_read_only=on" in options
