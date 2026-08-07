from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from prodkit_storage.redis.cache import AsyncCache, SyncCache
from prodkit_storage.redis.keys import KeyBuilder


class SyncPipeline:
    def __init__(self, client: FakeRedis) -> None:
        self.client = client
        self.operations: list[Callable[[], Any]] = []

    def __enter__(self) -> SyncPipeline:
        return self

    def __exit__(self, *args: Any) -> None:
        del args

    def set(self, *args: Any, **kwargs: Any) -> SyncPipeline:
        self.operations.append(lambda: self.client.set(*args, **kwargs))
        return self

    def sadd(self, *args: Any) -> SyncPipeline:
        self.operations.append(lambda: self.client.sadd(*args))
        return self

    def expire(self, *args: Any, **kwargs: Any) -> SyncPipeline:
        self.operations.append(lambda: self.client.expire(*args, **kwargs))
        return self

    def delete(self, *args: Any) -> SyncPipeline:
        self.operations.append(lambda: self.client.delete(*args))
        return self

    def execute(self) -> list[Any]:
        return [operation() for operation in self.operations]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sets: dict[str, set[Any]] = {}

    def pipeline(self, *, transaction: bool) -> SyncPipeline:
        assert transaction
        return SyncPipeline(self)

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        del ex, px
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += int(self.values.pop(key, None) is not None)
            deleted += int(self.sets.pop(key, None) is not None)
        return deleted

    def sadd(self, key: str, value: Any) -> int:
        members = self.sets.setdefault(key, set())
        before = len(members)
        members.add(value)
        return int(len(members) != before)

    def smembers(self, key: str) -> set[Any]:
        return set(self.sets.get(key, set()))

    def expire(
        self,
        key: str,
        ttl: int,
        *,
        nx: bool = False,
        gt: bool = False,
    ) -> bool:
        del ttl, nx, gt
        return key in self.values or key in self.sets

    def eval(self, script: str, number_of_keys: int, key: str, token: str, *args: Any) -> int:
        del number_of_keys
        if self.values.get(key) != token:
            return 0
        if "pexpire" in script:
            return int(bool(args and int(args[0]) > 0))
        self.values.pop(key, None)
        return 1


class AsyncPipeline:
    def __init__(self, client: AsyncFakeRedis) -> None:
        self.client = client
        self.operations: list[Callable[[], Any]] = []

    async def __aenter__(self) -> AsyncPipeline:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args

    def set(self, *args: Any, **kwargs: Any) -> AsyncPipeline:
        self.operations.append(lambda: self.client._set(*args, **kwargs))
        return self

    def sadd(self, *args: Any) -> AsyncPipeline:
        self.operations.append(lambda: self.client._sadd(*args))
        return self

    def expire(self, *args: Any, **kwargs: Any) -> AsyncPipeline:
        self.operations.append(lambda: self.client._expire(*args, **kwargs))
        return self

    def delete(self, *args: Any) -> AsyncPipeline:
        self.operations.append(lambda: self.client._delete(*args))
        return self

    async def execute(self) -> list[Any]:
        return [operation() for operation in self.operations]


class AsyncFakeRedis(FakeRedis):
    def pipeline(self, *, transaction: bool) -> AsyncPipeline:
        assert transaction
        return AsyncPipeline(self)

    def _set(self, *args: Any, **kwargs: Any) -> bool:
        return super().set(*args, **kwargs)

    def _delete(self, *args: Any) -> int:
        return super().delete(*args)

    def _sadd(self, *args: Any) -> int:
        return super().sadd(*args)

    def _expire(self, *args: Any, **kwargs: Any) -> bool:
        return super().expire(*args, **kwargs)

    async def get(self, key: str) -> Any:
        return super().get(key)

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return super().set(*args, **kwargs)

    async def delete(self, *keys: str) -> int:
        return super().delete(*keys)

    async def smembers(self, key: str) -> set[Any]:
        return super().smembers(key)

    async def eval(self, *args: Any) -> int:
        return super().eval(*args)



def test_sync_cache_set_get_tag_invalidation_and_stampede_lock() -> None:
    client = FakeRedis()
    keys = KeyBuilder("test")
    cache = SyncCache(client, keys, default_ttl_seconds=60, jitter_ratio=0)
    key = keys.build("customer", "1")

    cache.set(key, {"name": "Ada"}, tags=["customers"])
    assert cache.get(key) == {"name": "Ada"}
    assert cache.invalidate_tag("customers") == 1
    assert cache.get(key, default="missing") == "missing"

    loads = 0

    def loader() -> dict[str, int]:
        nonlocal loads
        loads += 1
        return {"value": loads}

    assert cache.get_or_set(key, loader) == {"value": 1}
    assert cache.get_or_set(key, loader) == {"value": 1}
    assert loads == 1
    assert cache.delete(key) == 1
    assert cache.delete() == 0


@pytest.mark.asyncio
async def test_async_cache_set_get_tag_invalidation_and_stampede_lock() -> None:
    client = AsyncFakeRedis()
    keys = KeyBuilder("test")
    cache = AsyncCache(client, keys, default_ttl_seconds=60, jitter_ratio=0)
    key = keys.build("customer", "2")

    await cache.set(key, {"name": "Grace"}, tags=["customers"])
    assert await cache.get(key) == {"name": "Grace"}
    assert await cache.invalidate_tag("customers") == 1
    assert await cache.get(key, default="missing") == "missing"

    loads = 0

    async def loader() -> dict[str, int]:
        nonlocal loads
        loads += 1
        return {"value": loads}

    assert await cache.get_or_set(key, loader) == {"value": 1}
    assert await cache.get_or_set(key, loader) == {"value": 1}
    assert loads == 1
    assert await cache.delete(key) == 1
    assert await cache.delete() == 0
