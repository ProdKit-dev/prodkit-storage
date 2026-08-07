"""JSON cache with stampede protection, TTL jitter, and tag invalidation."""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

import orjson
from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient

from prodkit_storage.redis.keys import KeyBuilder
from prodkit_storage.redis.locks import AsyncRedisLock, RedisLock

T = TypeVar("T")
_MISS = object()


class JsonCodec:
    def dumps(self, value: Any) -> bytes:
        return orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_UTC_Z)

    def loads(self, value: bytes | str) -> Any:
        return orjson.loads(value)


class SyncCache:
    def __init__(
        self,
        client: Redis,
        keys: KeyBuilder,
        *,
        default_ttl_seconds: int = 300,
        jitter_ratio: float = 0.1,
        codec: JsonCodec | None = None,
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive")
        if not 0 <= jitter_ratio <= 0.5:
            raise ValueError("jitter_ratio must be between 0 and 0.5")
        self.client = client
        self.keys = keys
        self.default_ttl_seconds = default_ttl_seconds
        self.jitter_ratio = jitter_ratio
        self.codec = codec or JsonCodec()

    def get(self, key: str, *, default: Any = None) -> Any:
        value = self.client.get(key)
        return default if value is None else self.codec.loads(value)

    def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
        tags: Iterable[str] = (),
    ) -> None:
        ttl = self._ttl(ttl_seconds)
        encoded = self.codec.dumps(value)
        tag_list = list(tags)
        with self.client.pipeline(transaction=True) as pipe:
            pipe.set(key, encoded, ex=ttl)
            for tag in tag_list:
                tag_key = self.keys.tag(tag)
                pipe.sadd(tag_key, key)
                # Preserve the longest member TTL: NX handles a new tag set,
                # while GT extends an existing shorter expiration.
                pipe.expire(tag_key, ttl + 60, nx=True)
                pipe.expire(tag_key, ttl + 60, gt=True)
            pipe.execute()

    def delete(self, *keys: str) -> int:
        return int(self.client.delete(*keys)) if keys else 0

    def invalidate_tag(self, tag: str) -> int:
        tag_key = self.keys.tag(tag)
        members = self.client.smembers(tag_key)
        decoded = [m.decode() if isinstance(m, bytes) else m for m in members]
        if not decoded:
            return int(self.client.delete(tag_key))
        with self.client.pipeline(transaction=True) as pipe:
            pipe.delete(*decoded)
            pipe.delete(tag_key)
            results = pipe.execute()
        return int(results[0])

    def get_or_set(
        self,
        key: str,
        loader: Callable[[], T],
        *,
        ttl_seconds: int | None = None,
        tags: Iterable[str] = (),
        lock_ttl_ms: int = 30_000,
        lock_wait_seconds: float = 5.0,
    ) -> T:
        cached = self.get(key, default=_MISS)
        if cached is not _MISS:
            return cached
        lock = RedisLock(
            self.client,
            f"{key}:lock",
            ttl_ms=lock_ttl_ms,
            blocking_timeout_seconds=lock_wait_seconds,
        )
        with lock:
            cached = self.get(key, default=_MISS)
            if cached is not _MISS:
                return cached
            value = loader()
            self.set(key, value, ttl_seconds=ttl_seconds, tags=tags)
            return value

    def _ttl(self, ttl_seconds: int | None) -> int:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        spread = int(ttl * self.jitter_ratio)
        return max(1, ttl + random.randint(-spread, spread))  # noqa: S311


class AsyncCache:
    def __init__(
        self,
        client: AsyncRedisClient,
        keys: KeyBuilder,
        *,
        default_ttl_seconds: int = 300,
        jitter_ratio: float = 0.1,
        codec: JsonCodec | None = None,
    ) -> None:
        if default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive")
        if not 0 <= jitter_ratio <= 0.5:
            raise ValueError("jitter_ratio must be between 0 and 0.5")
        self.client = client
        self.keys = keys
        self.default_ttl_seconds = default_ttl_seconds
        self.jitter_ratio = jitter_ratio
        self.codec = codec or JsonCodec()

    async def get(self, key: str, *, default: Any = None) -> Any:
        value = await self.client.get(key)
        return default if value is None else self.codec.loads(value)

    async def set(
        self,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
        tags: Iterable[str] = (),
    ) -> None:
        ttl = self._ttl(ttl_seconds)
        encoded = self.codec.dumps(value)
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.set(key, encoded, ex=ttl)
            for tag in tags:
                tag_key = self.keys.tag(tag)
                pipe.sadd(tag_key, key)
                # Preserve the longest member TTL: NX handles a new tag set,
                # while GT extends an existing shorter expiration.
                pipe.expire(tag_key, ttl + 60, nx=True)
                pipe.expire(tag_key, ttl + 60, gt=True)
            await pipe.execute()

    async def delete(self, *keys: str) -> int:
        return int(await self.client.delete(*keys)) if keys else 0

    async def invalidate_tag(self, tag: str) -> int:
        tag_key = self.keys.tag(tag)
        members = await self.client.smembers(tag_key)
        decoded = [m.decode() if isinstance(m, bytes) else m for m in members]
        if not decoded:
            return int(await self.client.delete(tag_key))
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.delete(*decoded)
            pipe.delete(tag_key)
            results = await pipe.execute()
        return int(results[0])

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
        *,
        ttl_seconds: int | None = None,
        tags: Iterable[str] = (),
        lock_ttl_ms: int = 30_000,
        lock_wait_seconds: float = 5.0,
    ) -> T:
        cached = await self.get(key, default=_MISS)
        if cached is not _MISS:
            return cached
        lock = AsyncRedisLock(
            self.client,
            f"{key}:lock",
            ttl_ms=lock_ttl_ms,
            blocking_timeout_seconds=lock_wait_seconds,
        )
        async with lock:
            cached = await self.get(key, default=_MISS)
            if cached is not _MISS:
                return cached
            value = await loader()
            await self.set(key, value, ttl_seconds=ttl_seconds, tags=tags)
            return value

    def _ttl(self, ttl_seconds: int | None) -> int:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        spread = int(ttl * self.jitter_ratio)
        return max(1, ttl + random.randint(-spread, spread))  # noqa: S311
