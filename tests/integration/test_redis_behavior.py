from __future__ import annotations

import pytest

from prodkit_storage.config import StorageSettings
from prodkit_storage.exceptions import IdempotencyConflictError
from prodkit_storage.redis.cache import SyncCache
from prodkit_storage.redis.idempotency import SyncIdempotencyStore, request_fingerprint
from prodkit_storage.redis.keys import KeyBuilder
from prodkit_storage.redis.locks import RedisLock
from prodkit_storage.redis.rate_limit import SyncRateLimiter
from prodkit_storage.redis.runtime import SyncRedis
from prodkit_storage.redis.streams import SyncStreamPublisher

pytestmark = pytest.mark.integration


def test_cache_tag_invalidation_is_atomic_server_side() -> None:
    runtime = SyncRedis(StorageSettings(environment="test"))
    try:
        runtime.client.flushdb()
        keys = KeyBuilder("integration")
        cache = SyncCache(runtime.client, keys, default_ttl_seconds=60, jitter_ratio=0)
        first = keys.build("customer", "1")
        second = keys.build("customer", "2")
        cache.set(first, {"id": 1}, tags=["customers"])
        cache.set(second, {"id": 2}, tags=["customers"])

        assert cache.invalidate_tag("customers") == 2
        assert cache.get(first) is None
        assert cache.get(second) is None
        assert runtime.client.exists(keys.tag("customers")) == 0
    finally:
        runtime.close()


def test_idempotency_lock_rate_limit_and_stream_paths() -> None:
    runtime = SyncRedis(StorageSettings(environment="test"))
    try:
        runtime.client.flushdb()
        keys = KeyBuilder("integration")

        store = SyncIdempotencyStore(runtime.client)
        key = keys.build("idempotency", "request-1")
        fingerprint = request_fingerprint({"amount": 100})
        started = store.begin(key, fingerprint)
        assert started.status == "started"
        assert started.token is not None
        store.complete(key, started.token, fingerprint, {"status": "ok"})
        replay = store.begin(key, fingerprint)
        assert replay.status == "completed"
        assert replay.response == {"status": "ok"}
        with pytest.raises(IdempotencyConflictError):
            store.begin(key, request_fingerprint({"amount": 101}))

        lock_key = keys.build("lock", "resource")
        first = RedisLock(runtime.client, lock_key, ttl_ms=5_000)
        second = RedisLock(runtime.client, lock_key, ttl_ms=5_000, required=False)
        assert first.acquire()
        assert second.acquire() is False
        assert first.release()
        assert second.acquire()
        assert second.release()

        limiter = SyncRateLimiter(runtime.client)
        limit_key = keys.build("rate", "user-1")
        first_decision = limiter.check(
            limit_key,
            capacity=2,
            refill_rate_per_second=1,
        )
        second_decision = limiter.check(
            limit_key,
            capacity=2,
            refill_rate_per_second=1,
        )
        third_decision = limiter.check(
            limit_key,
            capacity=2,
            refill_rate_per_second=1,
        )
        assert first_decision.allowed
        assert second_decision.allowed
        assert not third_decision.allowed
        assert third_decision.retry_after_ms > 0

        publisher = SyncStreamPublisher(runtime.client)
        stream = keys.build("stream", "events")
        message_id = publisher.publish(stream, {"type": "integration.test"}, maxlen=100)
        assert message_id
        assert runtime.client.xlen(stream) == 1
    finally:
        runtime.close()
