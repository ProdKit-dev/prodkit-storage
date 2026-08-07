from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import column, create_engine, select

from prodkit_storage import cli
from prodkit_storage.config import StorageSettings
from prodkit_storage.database import health, observability, runtime
from prodkit_storage.spatial.queries import (
    bounding_box,
    contains,
    distance_meters,
    intersects,
    make_point,
    within_distance,
)
from prodkit_storage.spatial.types import geography, geometry, point_geometry


class FakePool:
    def __init__(self) -> None:
        self.disconnected = False

    def status(self) -> str:
        return "Pool size: 10"

    def size(self) -> int:
        return 10

    def checkedin(self) -> int:
        return 8

    def checkedout(self) -> int:
        return 2

    def overflow(self) -> int:
        return 0


class FakeConnection:
    def __init__(self, values: list[Any] | None = None, error: Exception | None = None) -> None:
        self.values = values or []
        self.error = error

    def scalar(self, statement: Any) -> Any:
        del statement
        if self.error is not None:
            raise self.error
        return self.values.pop(0)


class FakeConnectContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *args: object) -> None:
        del args


class FakeEngine:
    def __init__(self, connection: FakeConnection | None = None) -> None:
        self.pool = FakePool()
        self.connection = connection or FakeConnection(["18.0", "3.6.1"])
        self.disposed = False

    def connect(self) -> FakeConnectContext:
        return FakeConnectContext(self.connection)

    def dispose(self) -> None:
        self.disposed = True


class FakeAsyncConnection:
    def __init__(self, values: list[Any] | None = None, error: Exception | None = None) -> None:
        self.values = values or []
        self.error = error

    async def scalar(self, statement: Any) -> Any:
        del statement
        if self.error is not None:
            raise self.error
        return self.values.pop(0)


class FakeAsyncConnectContext:
    def __init__(self, connection: FakeAsyncConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeAsyncConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeAsyncEngine:
    def __init__(self, connection: FakeAsyncConnection | None = None) -> None:
        self.sync_engine = FakeEngine()
        self.connection = connection or FakeAsyncConnection(["18.0", "3.6.1"])
        self.disposed = False

    def connect(self) -> FakeAsyncConnectContext:
        return FakeAsyncConnectContext(self.connection)

    async def dispose(self) -> None:
        self.disposed = True


def test_sync_database_health_success_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([1.0, 1.01, 2.0, 2.01, 3.0, 3.01])
    monkeypatch.setattr(health.time, "perf_counter", lambda: next(times))

    result = health.check_sync_database(FakeEngine())  # type: ignore[arg-type]
    assert result.healthy is True
    assert result.server_version == "18.0"
    assert result.postgis_version == "3.6.1"
    assert result.pool["checkedout"] == 2

    no_postgis = health.check_sync_database(
        FakeEngine(FakeConnection(["18.0", None]))  # type: ignore[arg-type]
    )
    assert no_postgis.healthy is False
    assert "PostGIS extension" in (no_postgis.error or "")

    optional_postgis = health.check_sync_database(
        FakeEngine(FakeConnection(["18.0", None])),  # type: ignore[arg-type]
        require_postgis=False,
    )
    assert optional_postgis.healthy is True
    assert optional_postgis.postgis_version is None


@pytest.mark.asyncio
async def test_async_database_health_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([1.0, 1.01, 2.0, 2.01])
    monkeypatch.setattr(health.time, "perf_counter", lambda: next(times))

    result = await health.check_async_database(FakeAsyncEngine())  # type: ignore[arg-type]
    assert result.healthy is True
    assert result.pool["size"] == 10

    failed = await health.check_async_database(
        FakeAsyncEngine(FakeAsyncConnection(error=OSError("offline")))  # type: ignore[arg-type]
    )
    assert failed.healthy is False
    assert failed.error == "OSError: offline"


def test_runtime_engine_options_and_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = StorageSettings(
        read_database_url="postgresql://reader:secret@db/read",
        async_read_database_url="postgresql://async-reader:secret@db/read",
        database_schema="app",
    )
    sync_calls: list[tuple[Any, dict[str, Any]]] = []
    async_calls: list[tuple[Any, dict[str, Any]]] = []
    sync_engine = FakeEngine()
    async_engine = FakeAsyncEngine()

    def fake_create_engine(url: Any, **kwargs: Any) -> FakeEngine:
        sync_calls.append((url, kwargs))
        return sync_engine

    def fake_create_async_engine(url: Any, **kwargs: Any) -> FakeAsyncEngine:
        async_calls.append((url, kwargs))
        return async_engine

    monkeypatch.setattr(runtime, "create_engine", fake_create_engine)
    monkeypatch.setattr(runtime, "create_async_engine", fake_create_async_engine)

    assert "search_path=app,public" in runtime._postgres_options(settings, readonly=False)
    assert "default_transaction_read_only=on" in runtime._postgres_options(
        settings, readonly=True
    )

    assert runtime._create_sync_engine(settings, readonly=True) is sync_engine
    sync_url, sync_kwargs = sync_calls[0]
    assert sync_url.drivername == "postgresql+psycopg"
    assert sync_kwargs["connect_args"]["application_name"].endswith("-read")
    assert "default_transaction_read_only=on" in sync_kwargs["connect_args"]["options"]

    assert runtime._create_async_engine(settings, readonly=True) is async_engine
    async_url, async_kwargs = async_calls[0]
    assert async_url.drivername == "postgresql+asyncpg"
    assert async_kwargs["connect_args"]["server_settings"][
        "default_transaction_read_only"
    ] == "on"


class FakeSyncSession:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))

    @contextmanager
    def begin(self) -> Iterator[None]:
        yield

    def __enter__(self) -> FakeSyncSession:
        return self

    def __exit__(self, *args: object) -> None:
        del args


class FakeSyncFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeSyncSession] = []

    def __call__(self) -> FakeSyncSession:
        session = FakeSyncSession()
        self.sessions.append(session)
        return session

    @contextmanager
    def begin(self) -> Iterator[FakeSyncSession]:
        session = FakeSyncSession()
        self.sessions.append(session)
        yield session


class FakeAsyncSession:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def __aenter__(self) -> FakeAsyncSession:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeAsyncFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeAsyncSession] = []

    def __call__(self) -> FakeAsyncSession:
        session = FakeAsyncSession()
        self.sessions.append(session)
        return session

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FakeAsyncSession]:
        session = FakeAsyncSession()
        self.sessions.append(session)
        yield session


def test_sync_database_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    write_engine = FakeEngine()
    read_engine = FakeEngine()
    engines = iter([write_engine, read_engine])
    factories = [FakeSyncFactory(), FakeSyncFactory()]

    monkeypatch.setattr(runtime, "_create_sync_engine", lambda *args, **kwargs: next(engines))
    monkeypatch.setattr(runtime, "sessionmaker", lambda **kwargs: factories.pop(0))
    monkeypatch.setattr(runtime, "install_query_observer", lambda *args: None)

    database = runtime.SyncDatabase(
        StorageSettings(read_database_url="postgresql://reader:secret@db/read")
    )
    with database.session() as session:
        assert isinstance(session, FakeSyncSession)
    with database.read_session() as session:
        assert isinstance(session, FakeSyncSession)
    with database.transaction() as session:
        assert isinstance(session, FakeSyncSession)
    with database.read_transaction() as session:
        assert session.executed == []

    database.dispose()
    assert write_engine.disposed is True
    assert read_engine.disposed is True


@pytest.mark.asyncio
async def test_async_database_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    write_engine = FakeAsyncEngine()
    read_engine = FakeAsyncEngine()
    engines = iter([write_engine, read_engine])
    factories = [FakeAsyncFactory(), FakeAsyncFactory()]

    monkeypatch.setattr(runtime, "_create_async_engine", lambda *args, **kwargs: next(engines))
    monkeypatch.setattr(runtime, "async_sessionmaker", lambda **kwargs: factories.pop(0))
    monkeypatch.setattr(runtime, "install_query_observer", lambda *args: None)

    database = runtime.AsyncDatabase(
        StorageSettings(async_read_database_url="postgresql://reader:secret@db/read")
    )
    async with database.session() as session:
        assert isinstance(session, FakeAsyncSession)
    async with database.read_session() as session:
        assert isinstance(session, FakeAsyncSession)
    async with database.transaction() as session:
        assert isinstance(session, FakeAsyncSession)
    async with database.read_transaction() as session:
        assert session.executed == []

    await database.dispose()
    assert write_engine.disposed is True
    assert read_engine.disposed is True


def test_observer_logs_slow_query_and_discards_timer(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_engine("sqlite://")
    settings = StorageSettings(slow_query_threshold_ms=1, log_query_parameters=True)
    times = iter([1.0, 1.1])
    monkeypatch.setattr(observability.time, "perf_counter", lambda: next(times))
    observability.install_query_observer(engine, settings)
    observability.install_query_observer(engine, settings)

    with caplog.at_level("WARNING", logger="prodkit_storage.sql"):
        with engine.connect() as connection:
            connection.execute(select(1))

    record = next(item for item in caplog.records if item.message == "slow database query")
    assert record.duration_ms == 100.0
    assert record.statement
    assert record.parameters is not None

    connection = SimpleNamespace(info={"prodkit_query_started": [1.0]})
    observability._discard_query_timer(connection)
    observability._discard_query_timer(connection)
    assert connection.info["prodkit_query_started"] == []
    engine.dispose()


def test_cli_configuration_parser_and_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = StorageSettings()
    config = cli._alembic_config(settings)
    assert Path(config.get_main_option("script_location")).name == "alembic"
    assert "postgresql+psycopg" in config.get_main_option("sqlalchemy.url")
    assert "postgresql+asyncpg" in cli._alembic_config(
        settings, async_driver=True
    ).get_main_option("sqlalchemy.url")

    parser = cli.build_parser()
    assert parser.parse_args(["doctor", "--async"]).async_mode is True
    assert parser.parse_args(["upgrade"]).revision == "head"
    assert parser.parse_args(["downgrade", "base"]).revision == "base"

    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(cli, "StorageSettings", lambda: settings)
    monkeypatch.setattr(
        cli.command,
        "upgrade",
        lambda config, revision: calls.append(("up", revision)),
    )
    monkeypatch.setattr(
        cli.command, "downgrade", lambda config, revision: calls.append(("down", revision))
    )
    monkeypatch.setattr(
        cli.command, "current", lambda config, verbose: calls.append(("current", verbose))
    )
    assert cli.main(["upgrade", "head"]) == 0
    assert cli.main(["downgrade", "base"]) == 0
    assert cli.main(["current"]) == 0
    assert calls == [("up", "head"), ("down", "base"), ("current", True)]


def test_spatial_expression_factories() -> None:
    point_type = point_geometry(nullable=False)
    geometry_type = geometry("POLYGON", srid=3857, dimension=3)
    geography_type = geography("POINT")
    assert point_type.geometry_type == "POINT"
    assert point_type.nullable is False
    assert geometry_type.geometry_type == "POLYGON"
    assert geometry_type.dimension == 3
    assert geography_type.geometry_type == "POINT"

    location = column("location")
    assert "ST_MakePoint" in str(make_point(29.0, 41.0))
    assert "ST_Distance" in str(distance_meters(location, 29.0, 41.0))
    assert "ST_DWithin" in str(within_distance(location, 29.0, 41.0, 1000))
    assert "ST_Intersects" in str(intersects(location, "shape"))
    assert "ST_Contains" in str(contains(location, "shape"))
    assert "ST_MakeEnvelope" in str(bounding_box(28.0, 40.0, 30.0, 42.0))

    with pytest.raises(ValueError, match="radius_meters"):
        within_distance(location, 29.0, 41.0, -1)
    with pytest.raises(ValueError, match="minimums"):
        bounding_box(30.0, 40.0, 29.0, 42.0)
