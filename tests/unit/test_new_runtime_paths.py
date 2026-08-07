from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import String, literal, select
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import RequestContext, get_request_context
from prodkit_storage.database.base import Base, UUIDPrimaryKeyMixin
from prodkit_storage.database.observability import StorageTelemetry, instrument_sqlalchemy
from prodkit_storage.database.pagination import paginate_offset_async, paginate_offset_sync
from prodkit_storage.database.repository import AsyncRepository, SyncRepository
from prodkit_storage.integrations.fastapi.context import RequestContextMiddleware
from prodkit_storage.integrations.fastapi.database import (
    create_database_dependency,
    create_read_session_dependency,
    create_write_session_dependency,
)
from prodkit_storage.redis.runtime import AsyncRedis, ObservedRedis, SyncRedis, _command_name


class ExtendedCustomer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "test_extended_customers"

    name: Mapped[str] = mapped_column(String(100))


class UniqueScalarResult:
    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.closed = False

    def unique(self) -> UniqueScalarResult:
        return self

    def all(self) -> list[Any]:
        return self.values

    def __iter__(self):
        return iter(self.values)

    def close(self) -> None:
        self.closed = True


class ExecuteResult:
    rowcount = 3

    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def unique(self) -> ExecuteResult:
        return self

    def scalar_one(self) -> Any:
        return self.values[0]

    def scalar_one_or_none(self) -> Any:
        return self.values[0] if self.values else None

    def scalars(self) -> UniqueScalarResult:
        return UniqueScalarResult(self.values)


class RichSyncSession:
    def __init__(self, entity: Any) -> None:
        self.entity = entity
        self.added: list[Any] = []
        self.flushed = 0
        self.refreshed: list[Any] = []
        self.scalar_values = [2]

    def add(self, value: Any) -> None:
        self.added.append(value)

    def add_all(self, values: list[Any]) -> None:
        self.added.extend(values)

    def flush(self) -> None:
        self.flushed += 1

    def refresh(self, value: Any) -> None:
        self.refreshed.append(value)

    def execute(self, statement: Any, parameters: Any = None) -> ExecuteResult:
        del statement, parameters
        return ExecuteResult([self.entity])

    def scalars(self, statement: Any) -> UniqueScalarResult:
        del statement
        return UniqueScalarResult([self.entity])

    def scalar(self, statement: Any) -> Any:
        del statement
        return self.scalar_values.pop(0) if self.scalar_values else self.entity

    def delete(self, value: Any) -> None:
        self.added.append(("deleted", value))


class AsyncStreamResult:
    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.closed = False

    def __aiter__(self):
        async def iterator():
            for value in self.values:
                yield value

        return iterator()

    async def close(self) -> None:
        self.closed = True


class RichAsyncSession(RichSyncSession):
    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, value: Any) -> None:
        self.refreshed.append(value)

    async def execute(self, statement: Any, parameters: Any = None) -> ExecuteResult:
        return super().execute(statement, parameters)

    async def scalars(self, statement: Any) -> UniqueScalarResult:
        return super().scalars(statement)

    async def scalar(self, statement: Any) -> Any:
        return super().scalar(statement)

    async def delete(self, value: Any) -> None:
        super().delete(value)

    async def stream_scalars(self, statement: Any) -> AsyncStreamResult:
        del statement
        return AsyncStreamResult([self.entity])


class OffsetSession:
    def __init__(self, values: list[Any], total: int) -> None:
        self.values = values
        self.total = total
        self.last_scalar_statement: Any = None

    def scalar(self, statement: Any) -> int:
        self.last_scalar_statement = statement
        return self.total

    def scalars(self, statement: Any) -> UniqueScalarResult:
        del statement
        return UniqueScalarResult(self.values)


class AsyncOffsetSession(OffsetSession):
    async def scalar(self, statement: Any) -> int:
        return super().scalar(statement)

    async def scalars(self, statement: Any) -> UniqueScalarResult:
        return super().scalars(statement)


def make_customer() -> ExtendedCustomer:
    return ExtendedCustomer(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="Ada",
    )


def test_rich_sync_repository_and_offset_paths() -> None:
    entity = make_customer()
    session = RichSyncSession(entity)
    repository = SyncRepository(session, ExtendedCustomer)  # type: ignore[arg-type]
    assert repository.create(entity, flush=True, refresh=True) is entity
    assert repository.update(entity, values={"name": "Grace"}, flush=True).name == "Grace"
    assert repository.get_one(select(ExtendedCustomer)) is entity
    assert repository.get_one_or_none(select(ExtendedCustomer)) is entity
    assert repository.get_all(select(ExtendedCustomer)) == [entity]
    assert list(repository.stream(yield_per=10)) == [entity]
    assert repository.bulk_insert([{"name": "A"}]) == 3
    assert repository.bulk_update({"name": "B"}, ExtendedCustomer.name == "A") == 3

    offset_session = OffsetSession([entity], 3)
    explicit_count = select(literal(3))
    page = paginate_offset_sync(
        offset_session,  # type: ignore[arg-type]
        select(ExtendedCustomer),
        page=2,
        limit=2,
        count_statement=explicit_count,
    )
    assert offset_session.last_scalar_statement is explicit_count
    assert page.total_pages == 2
    assert page.has_previous_page


@pytest.mark.asyncio
async def test_rich_async_repository_and_offset_paths() -> None:
    entity = make_customer()
    session = RichAsyncSession(entity)
    repository = AsyncRepository(session, ExtendedCustomer)  # type: ignore[arg-type]
    assert await repository.create(entity, flush=True, refresh=True) is entity
    assert (await repository.update(entity, values={"name": "Grace"}, flush=True)).name == "Grace"
    assert await repository.get_one(select(ExtendedCustomer)) is entity
    assert await repository.get_one_or_none(select(ExtendedCustomer)) is entity
    assert await repository.get_all(select(ExtendedCustomer)) == [entity]
    streamed = [item async for item in repository.stream(yield_per=10)]
    assert streamed == [entity]
    assert await repository.bulk_insert([{"name": "A"}]) == 3
    assert await repository.bulk_update({"name": "B"}) == 3

    offset_session = AsyncOffsetSession([entity], 1)
    explicit_count = select(literal(1))
    page = await paginate_offset_async(
        offset_session,  # type: ignore[arg-type]
        select(ExtendedCustomer),
        count_statement=explicit_count,
    )
    assert offset_session.last_scalar_statement is explicit_count
    assert page.items == [entity]
    assert page.total_count == 1


class FakeAsyncDatabase:
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[str]:
        yield "write"

    @asynccontextmanager
    async def read_transaction(self) -> AsyncIterator[str]:
        yield "read"


@pytest.mark.asyncio
async def test_fastapi_database_dependencies() -> None:
    database = FakeAsyncDatabase()
    get_database = create_database_dependency(database)  # type: ignore[arg-type]
    assert await get_database() is database

    write_generator = create_write_session_dependency(database)()  # type: ignore[arg-type]
    assert await anext(write_generator) == "write"
    await write_generator.aclose()

    read_generator = create_read_session_dependency(database)()  # type: ignore[arg-type]
    assert await anext(read_generator) == "read"
    await read_generator.aclose()


@pytest.mark.asyncio
async def test_request_context_middleware() -> None:
    seen: list[RequestContext] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        del scope, receive, send
        seen.append(get_request_context())

    async def resolver(request: Any) -> RequestContext:
        del request
        return RequestContext(request_id="req-1", trace_id="trace-1")

    middleware = RequestContextMiddleware(app, resolver)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 123),
        "scheme": "http",
        "http_version": "1.1",
        "root_path": "",
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        del message

    await middleware(scope, receive, send)  # type: ignore[arg-type]
    assert seen[0].request_id == "req-1"
    assert get_request_context() == RequestContext()


def test_telemetry_and_redis_runtime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = StorageSettings(observability_enabled=True)
    telemetry = StorageTelemetry(settings)
    telemetry.record_query(1.0, component="test")
    telemetry.record_transaction(
        2.0,
        component="test",
        outcome="committed",
        read_only=False,
    )
    telemetry.record_redis(3.0, command="GET")
    telemetry.record_pool_event(component="test", event_name="checkout")
    telemetry.record_outbox(pending=1, dead=0, oldest_pending_age_seconds=4.0)
    with telemetry.start_span("test.span"):
        pass
    assert instrument_sqlalchemy(None, settings) is False  # type: ignore[arg-type]

    recorded: list[tuple[str, bool]] = []

    class Telemetry:
        def record_redis(self, duration: float, *, command: str, failed: bool) -> None:
            assert duration >= 0
            recorded.append((command, failed))

    # Avoid a live Redis connection: only exercise telemetry wrapper logic.
    monkeypatch.setattr(
        "redis.client.Redis.execute_command",
        lambda self, *args, **options: b"ok",
    )
    client = ObservedRedis(telemetry=Telemetry())  # type: ignore[arg-type]
    assert client.execute_command("GET", "key") == b"ok"
    assert recorded == [("GET", False)]
    assert _command_name((b"set",)) == "SET"
    assert _command_name(()) == "UNKNOWN"

    sync_runtime = SyncRedis(StorageSettings())
    assert sync_runtime.client.connection_pool.connection_kwargs["client_name"].endswith(
        "-redis"
    )
    sync_runtime.close()


@pytest.mark.asyncio
async def test_async_redis_runtime_close() -> None:
    runtime = AsyncRedis(StorageSettings())
    assert runtime.client.connection_pool.connection_kwargs["client_name"].endswith(
        "-async-redis"
    )
    await runtime.close()


def test_no_count_offset_pagination_uses_lookahead() -> None:
    first = make_customer()
    second = ExtendedCustomer(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        name="Grace",
    )
    page = paginate_offset_sync(
        OffsetSession([first, second], 0),  # type: ignore[arg-type]
        select(ExtendedCustomer),
        limit=1,
        include_total=False,
    )
    assert page.items == [first]
    assert page.has_next_page
    assert page.total_pages is None


def test_metric_attributes_exclude_request_cardinality() -> None:
    from prodkit_storage.context import request_context

    telemetry = StorageTelemetry(StorageSettings())
    with request_context(
        RequestContext(
            tenant_id=UUID("00000000-0000-0000-0000-000000000010"),
            actor_id=UUID("00000000-0000-0000-0000-000000000011"),
            request_id="request-high-cardinality",
            trace_id="trace-high-cardinality",
        )
    ):
        metric_attributes = telemetry.metric_attributes(component="database")
        trace_attributes = telemetry.trace_attributes(component="database")
    assert "tenant.id" not in metric_attributes
    assert "request.id" not in metric_attributes
    assert trace_attributes["tenant.id"].endswith("0010")
    assert trace_attributes["request.id"] == "request-high-cardinality"
