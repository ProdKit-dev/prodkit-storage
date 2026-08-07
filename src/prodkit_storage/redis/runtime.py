"""Sync and async Redis client lifecycle with process identity and telemetry."""

from __future__ import annotations

import logging
import time
from typing import Any

from redis import ConnectionPool, Redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedisClient
from redis.backoff import ExponentialWithJitterBackoff
from redis.retry import Retry

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.observability import StorageTelemetry, get_telemetry

logger = logging.getLogger("prodkit_storage.redis")


class ObservedRedis(Redis):
    def __init__(self, *args: Any, telemetry: StorageTelemetry, **kwargs: Any) -> None:
        self._storage_telemetry = telemetry
        super().__init__(*args, **kwargs)

    def execute_command(self, *args: Any, **options: Any) -> Any:
        command = _command_name(args)
        started = time.perf_counter()
        failed = False
        try:
            return super().execute_command(*args, **options)  # type: ignore[no-untyped-call]
        except BaseException:
            failed = True
            raise
        finally:
            self._storage_telemetry.record_redis(
                (time.perf_counter() - started) * 1000,
                command=command,
                failed=failed,
            )


class ObservedAsyncRedis(AsyncRedisClient):
    def __init__(self, *args: Any, telemetry: StorageTelemetry, **kwargs: Any) -> None:
        self._storage_telemetry = telemetry
        super().__init__(*args, **kwargs)

    async def execute_command(self, *args: Any, **options: Any) -> Any:
        command = _command_name(args)
        started = time.perf_counter()
        failed = False
        try:
            return await super().execute_command(  # type: ignore[no-untyped-call]
                *args,
                **options,
            )
        except BaseException:
            failed = True
            raise
        finally:
            self._storage_telemetry.record_redis(
                (time.perf_counter() - started) * 1000,
                command=command,
                failed=failed,
            )


class SyncRedis:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.telemetry = get_telemetry(settings)
        pool = ConnectionPool.from_url(
            settings.redis_dsn,
            decode_responses=settings.redis_decode_responses,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            max_connections=settings.redis_max_connections,
            client_name=settings.client_name("redis"),
            retry=Retry(
                ExponentialWithJitterBackoff(), settings.redis_retry_attempts
            ),
            retry_on_timeout=True,
        )
        self.client = ObservedRedis(
            connection_pool=pool,
            telemetry=self.telemetry,
        )
        _instrument_redis(self.client, settings)

    def close(self) -> None:
        self.client.close()
        self.client.connection_pool.disconnect()


class AsyncRedis:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.telemetry = get_telemetry(settings)
        pool = AsyncConnectionPool.from_url(
            settings.redis_dsn,
            decode_responses=settings.redis_decode_responses,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            max_connections=settings.redis_max_connections,
            client_name=settings.client_name("async-redis"),
            retry=Retry(
                ExponentialWithJitterBackoff(), settings.redis_retry_attempts
            ),
            retry_on_timeout=True,
        )
        self.client = ObservedAsyncRedis(
            connection_pool=pool,
            telemetry=self.telemetry,
        )
        _instrument_redis(self.client, settings)

    async def close(self) -> None:
        await self.client.aclose()
        await self.client.connection_pool.disconnect()


def _instrument_redis(client: Any, settings: StorageSettings) -> bool:
    if not settings.observability_enabled or not settings.otel_redis_instrumentation:
        return False
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
    except ImportError:
        logger.warning("Redis OpenTelemetry instrumentation is not installed")
        return False
    RedisInstrumentor.instrument_client(client=client)
    return True


def _command_name(args: tuple[Any, ...]) -> str:
    if not args:
        return "UNKNOWN"
    first = args[0]
    if isinstance(first, bytes):
        return first.decode("ascii", errors="replace").upper()
    return str(first).upper()


__all__ = [
    "AsyncRedis",
    "ObservedAsyncRedis",
    "ObservedRedis",
    "SyncRedis",
]
