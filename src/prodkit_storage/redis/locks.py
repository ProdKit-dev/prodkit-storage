"""Token-safe Redis distributed locks for sync and async applications."""

from __future__ import annotations

import asyncio
import secrets
import time
from types import TracebackType
from typing import Self

from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient

from prodkit_storage.exceptions import LockNotAcquiredError

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_EXTEND_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLock:
    def __init__(
        self,
        client: Redis,
        key: str,
        *,
        ttl_ms: int = 30_000,
        blocking_timeout_seconds: float = 0,
        poll_interval_seconds: float = 0.05,
        required: bool = True,
    ) -> None:
        if ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive")
        if blocking_timeout_seconds < 0 or poll_interval_seconds <= 0:
            raise ValueError("lock wait values must be non-negative with a positive poll interval")
        self.client = client
        self.key = key
        self.ttl_ms = ttl_ms
        self.blocking_timeout_seconds = blocking_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.required = required
        self.token = secrets.token_urlsafe(24)
        self.acquired = False

    def acquire(self) -> bool:
        deadline = time.monotonic() + self.blocking_timeout_seconds
        while True:
            self.acquired = bool(self.client.set(self.key, self.token, nx=True, px=self.ttl_ms))
            if self.acquired:
                return True
            if time.monotonic() >= deadline:
                if self.required:
                    raise LockNotAcquiredError(f"could not acquire Redis lock {self.key}")
                return False
            time.sleep(self.poll_interval_seconds)

    def extend(self, ttl_ms: int | None = None) -> bool:
        if not self.acquired:
            return False
        new_ttl = self.ttl_ms if ttl_ms is None else ttl_ms
        if new_ttl <= 0:
            raise ValueError("ttl_ms must be positive")
        return bool(self.client.eval(_EXTEND_SCRIPT, 1, self.key, self.token, new_ttl))

    def release(self) -> bool:
        if not self.acquired:
            return False
        released = bool(self.client.eval(_RELEASE_SCRIPT, 1, self.key, self.token))
        self.acquired = False
        return released

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.release()


class AsyncRedisLock:
    def __init__(
        self,
        client: AsyncRedisClient,
        key: str,
        *,
        ttl_ms: int = 30_000,
        blocking_timeout_seconds: float = 0,
        poll_interval_seconds: float = 0.05,
        required: bool = True,
    ) -> None:
        if ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive")
        if blocking_timeout_seconds < 0 or poll_interval_seconds <= 0:
            raise ValueError("lock wait values must be non-negative with a positive poll interval")
        self.client = client
        self.key = key
        self.ttl_ms = ttl_ms
        self.blocking_timeout_seconds = blocking_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.required = required
        self.token = secrets.token_urlsafe(24)
        self.acquired = False

    async def acquire(self) -> bool:
        deadline = time.monotonic() + self.blocking_timeout_seconds
        while True:
            self.acquired = bool(
                await self.client.set(self.key, self.token, nx=True, px=self.ttl_ms)
            )
            if self.acquired:
                return True
            if time.monotonic() >= deadline:
                if self.required:
                    raise LockNotAcquiredError(f"could not acquire Redis lock {self.key}")
                return False
            await asyncio.sleep(self.poll_interval_seconds)

    async def extend(self, ttl_ms: int | None = None) -> bool:
        if not self.acquired:
            return False
        new_ttl = self.ttl_ms if ttl_ms is None else ttl_ms
        if new_ttl <= 0:
            raise ValueError("ttl_ms must be positive")
        return bool(await self.client.eval(_EXTEND_SCRIPT, 1, self.key, self.token, new_ttl))

    async def release(self) -> bool:
        if not self.acquired:
            return False
        released = bool(await self.client.eval(_RELEASE_SCRIPT, 1, self.key, self.token))
        self.acquired = False
        return released

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        await self.release()
