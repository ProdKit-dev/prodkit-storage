"""Redis liveness/readiness probes."""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient


@dataclass(frozen=True, slots=True)
class RedisHealth:
    healthy: bool
    latency_ms: float
    version: str | None
    error: str | None = None


def check_sync_redis(client: Redis) -> RedisHealth:
    started = time.perf_counter()
    try:
        client.ping()
        info = client.info(section="server")
        version = info.get("redis_version")
        return RedisHealth(
            True,
            (time.perf_counter() - started) * 1000,
            None if version is None else str(version),
        )
    except Exception as error:
        return RedisHealth(
            False,
            (time.perf_counter() - started) * 1000,
            None,
            f"{type(error).__name__}: {error}",
        )


async def check_async_redis(client: AsyncRedisClient) -> RedisHealth:
    started = time.perf_counter()
    try:
        await client.ping()
        info = await client.info(section="server")
        version = info.get("redis_version")
        return RedisHealth(
            True,
            (time.perf_counter() - started) * 1000,
            None if version is None else str(version),
        )
    except Exception as error:
        return RedisHealth(
            False,
            (time.perf_counter() - started) * 1000,
            None,
            f"{type(error).__name__}: {error}",
        )
