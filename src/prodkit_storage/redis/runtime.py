"""Sync and async Redis client lifecycle."""

from __future__ import annotations

from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient
from redis.backoff import ExponentialWithJitterBackoff
from redis.retry import Retry

from prodkit_storage.config import StorageSettings


class SyncRedis:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.client = Redis.from_url(
            settings.redis_dsn,
            decode_responses=settings.redis_decode_responses,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            max_connections=settings.redis_max_connections,
            retry=Retry(ExponentialWithJitterBackoff(), settings.redis_retry_attempts),
            retry_on_timeout=True,
        )

    def close(self) -> None:
        self.client.close()
        self.client.connection_pool.disconnect()


class AsyncRedis:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.client = AsyncRedisClient.from_url(
            settings.redis_dsn,
            decode_responses=settings.redis_decode_responses,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            max_connections=settings.redis_max_connections,
            retry=Retry(ExponentialWithJitterBackoff(), settings.redis_retry_attempts),
            retry_on_timeout=True,
        )

    async def close(self) -> None:
        await self.client.aclose()
