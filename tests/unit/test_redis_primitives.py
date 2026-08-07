from __future__ import annotations

from typing import Any

import orjson
import pytest

from prodkit_storage.exceptions import IdempotencyConflictError, LockNotAcquiredError
from prodkit_storage.redis.health import check_async_redis, check_sync_redis
from prodkit_storage.redis.idempotency import (
    AsyncIdempotencyStore,
    SyncIdempotencyStore,
    request_fingerprint,
)
from prodkit_storage.redis.locks import AsyncRedisLock, RedisLock
from prodkit_storage.redis.rate_limit import AsyncRateLimiter, SyncRateLimiter
from prodkit_storage.redis.streams import AsyncStreamPublisher, SyncStreamPublisher


class CoordinationRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.messages: list[tuple[str, dict[str, bytes], int | None]] = []
        self.fail_ping = False

    def set(
        self,
        key: str,
        value: Any,
        *,
        nx: bool = False,
        px: int | None = None,
    ) -> bool:
        del px
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, script: str, number_of_keys: int, key: str, *args: Any) -> Any:
        assert number_of_keys == 1
        if "HMGET" in script:
            return [1, 4, 0]
        if "local existing" in script:
            proposed = args[0]
            if key not in self.values:
                self.values[key] = proposed
            return self.values[key]
        if "decoded['token']" in script:
            current = self.values.get(key)
            if current is None:
                return 0
            decoded = orjson.loads(current)
            token = args[0]
            if decoded.get("token") != token:
                return -1
            if "redis.call('set'" in script:
                fingerprint = args[1]
                if decoded.get("fingerprint") != fingerprint:
                    return -1
                self.values[key] = args[2]
                return 1
            self.values.pop(key, None)
            return 1
        token = args[0]
        if self.values.get(key) != token:
            return 0
        if "pexpire" in script:
            return 1
        self.values.pop(key, None)
        return 1

    def xadd(
        self,
        stream: str,
        payload: dict[str, bytes],
        *,
        maxlen: int | None,
        approximate: bool,
    ) -> bytes:
        assert approximate
        self.messages.append((stream, payload, maxlen))
        return b"1-0"

    def ping(self) -> bool:
        if self.fail_ping:
            raise ConnectionError("unavailable")
        return True

    def info(self, *, section: str) -> dict[str, str]:
        assert section == "server"
        return {"redis_version": "8.8.1"}


class AsyncCoordinationRedis(CoordinationRedis):
    async def set(self, *args: Any, **kwargs: Any) -> bool:
        return super().set(*args, **kwargs)

    async def eval(self, *args: Any) -> Any:
        return super().eval(*args)

    async def xadd(self, *args: Any, **kwargs: Any) -> bytes:
        return super().xadd(*args, **kwargs)

    async def ping(self) -> bool:
        return super().ping()

    async def info(self, *, section: str) -> dict[str, str]:
        return super().info(section=section)


def test_sync_lock_acquire_extend_release_and_failure_modes() -> None:
    client = CoordinationRedis()
    lock = RedisLock(client, "lock:1")  # type: ignore[arg-type]
    assert lock.acquire()
    assert lock.extend(1000)
    assert lock.release()
    assert not lock.release()

    client.values["lock:2"] = "someone-else"
    with pytest.raises(LockNotAcquiredError):
        RedisLock(client, "lock:2").acquire()  # type: ignore[arg-type]
    assert not RedisLock(client, "lock:2", required=False).acquire()  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_lock_acquire_extend_release() -> None:
    client = AsyncCoordinationRedis()
    lock = AsyncRedisLock(client, "lock:async")  # type: ignore[arg-type]
    async with lock:
        assert lock.acquired
        assert await lock.extend(1000)
    assert not lock.acquired


def test_sync_idempotency_lifecycle_replay_and_conflict() -> None:
    client = CoordinationRedis()
    store = SyncIdempotencyStore(client)  # type: ignore[arg-type]
    fingerprint = request_fingerprint({"amount": 10, "currency": "USD"})

    started = store.begin("idem:1", fingerprint)
    assert started.status == "started"
    assert started.token
    assert store.begin("idem:1", fingerprint).status == "in_progress"

    with pytest.raises(IdempotencyConflictError):
        store.complete("idem:1", started.token, "wrong-fingerprint", {"status": 201})

    store.complete("idem:1", started.token, fingerprint, {"status": 201})
    replay = store.begin("idem:1", fingerprint)
    assert replay.status == "completed"
    assert replay.response == {"status": 201}

    with pytest.raises(IdempotencyConflictError):
        store.begin("idem:1", request_fingerprint({"amount": 11}))


def test_sync_idempotency_release_and_lost_lease() -> None:
    client = CoordinationRedis()
    store = SyncIdempotencyStore(client)  # type: ignore[arg-type]
    started = store.begin("idem:2", "fingerprint")
    assert started.token and store.release("idem:2", started.token)
    with pytest.raises(IdempotencyConflictError):
        store.complete("idem:2", started.token, "fingerprint", {})


@pytest.mark.asyncio
async def test_async_idempotency_lifecycle() -> None:
    client = AsyncCoordinationRedis()
    store = AsyncIdempotencyStore(client)  # type: ignore[arg-type]
    started = await store.begin("idem:async", "fingerprint")
    assert started.status == "started" and started.token
    await store.complete("idem:async", started.token, "fingerprint", {"ok": True})
    replay = await store.begin("idem:async", "fingerprint")
    assert replay.response == {"ok": True}
    assert not await store.release("missing", "token")


def test_rate_limits_streams_and_sync_health() -> None:
    client = CoordinationRedis()
    decision = SyncRateLimiter(client).check(  # type: ignore[arg-type]
        "rate:1", capacity=5, refill_rate_per_second=1
    )
    assert decision.allowed and decision.remaining == 4 and decision.retry_after_ms == 0
    with pytest.raises(ValueError):
        SyncRateLimiter(client).check(  # type: ignore[arg-type]
            "rate:1", capacity=1, refill_rate_per_second=1, cost=2
        )

    publisher = SyncStreamPublisher(client)  # type: ignore[arg-type]
    assert publisher.publish("events", {"type": "created"}, maxlen=100) == "1-0"
    assert client.messages[0][0] == "events"

    health = check_sync_redis(client)  # type: ignore[arg-type]
    assert health.healthy and health.version == "8.8.1"
    client.fail_ping = True
    assert not check_sync_redis(client).healthy  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_rate_limit_stream_and_health() -> None:
    client = AsyncCoordinationRedis()
    decision = await AsyncRateLimiter(client).check(  # type: ignore[arg-type]
        "rate:async", capacity=5, refill_rate_per_second=1
    )
    assert decision.allowed and decision.remaining == 4
    publisher = AsyncStreamPublisher(client)  # type: ignore[arg-type]
    assert await publisher.publish("events", {"type": "created"}) == "1-0"
    assert (await check_async_redis(client)).healthy  # type: ignore[arg-type]
    client.fail_ping = True
    assert not (await check_async_redis(client)).healthy  # type: ignore[arg-type]
