"""PostgreSQL liveness/readiness probes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    healthy: bool
    latency_ms: float
    server_version: str | None
    postgis_version: str | None
    pool: dict[str, Any]
    error: str | None = None


def check_sync_database(engine: Engine, *, require_postgis: bool = True) -> DatabaseHealth:
    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            server_version = str(connection.scalar(text("SHOW server_version")))
            postgis_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
            if require_postgis and postgis_version is None:
                raise RuntimeError("PostGIS extension is not enabled")
        return DatabaseHealth(
            healthy=True,
            latency_ms=(time.perf_counter() - started) * 1000,
            server_version=server_version,
            postgis_version=None if postgis_version is None else str(postgis_version),
            pool=_pool_status(engine),
        )
    except Exception as error:
        return DatabaseHealth(
            healthy=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            server_version=None,
            postgis_version=None,
            pool=_pool_status(engine),
            error=f"{type(error).__name__}: {error}",
        )


async def check_async_database(
    engine: AsyncEngine,
    *,
    require_postgis: bool = True,
) -> DatabaseHealth:
    started = time.perf_counter()
    try:
        async with engine.connect() as connection:
            server_version = str(await connection.scalar(text("SHOW server_version")))
            postgis_version = await connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
            if require_postgis and postgis_version is None:
                raise RuntimeError("PostGIS extension is not enabled")
        return DatabaseHealth(
            healthy=True,
            latency_ms=(time.perf_counter() - started) * 1000,
            server_version=server_version,
            postgis_version=None if postgis_version is None else str(postgis_version),
            pool=_pool_status(engine.sync_engine),
        )
    except Exception as error:
        return DatabaseHealth(
            healthy=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            server_version=None,
            postgis_version=None,
            pool=_pool_status(engine.sync_engine),
            error=f"{type(error).__name__}: {error}",
        )


def _pool_status(engine: Engine) -> dict[str, Any]:
    pool = engine.pool
    values: dict[str, Any] = {"status": pool.status()}
    for name in ("size", "checkedin", "checkedout", "overflow"):
        method = getattr(pool, name, None)
        if callable(method):
            values[name] = method()
    return values
