from datetime import timedelta
from typing import Any

import pytest

from prodkit_storage.models import OutboxEvent
from prodkit_storage.outbox import _validate_claim_options, mark_outbox_failed
from prodkit_storage.redis.cache import SyncCache
from prodkit_storage.redis.keys import KeyBuilder
from prodkit_storage.redis.locks import RedisLock


class FakeRedis:
    def eval(self, *args: Any) -> int:
        del args
        return 1


def test_cache_rejects_nonpositive_explicit_ttl() -> None:
    cache = SyncCache(FakeRedis(), KeyBuilder("test"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ttl_seconds"):
        cache._ttl(0)


def test_lock_rejects_nonpositive_extension() -> None:
    lock = RedisLock(FakeRedis(), "test:lock")  # type: ignore[arg-type]
    lock.acquired = True
    with pytest.raises(ValueError, match="ttl_ms"):
        lock.extend(0)


def test_outbox_failure_options_are_validated() -> None:
    event = OutboxEvent(topic="events", event_type="example", payload={})
    with pytest.raises(ValueError, match="max_attempts"):
        mark_outbox_failed(event, "failed", max_attempts=0)
    with pytest.raises(ValueError, match="base_delay_seconds"):
        mark_outbox_failed(event, "failed", base_delay_seconds=0)


def test_claim_options_are_validated() -> None:
    with pytest.raises(ValueError, match="worker_id"):
        _validate_claim_options(" ", 100, timedelta(minutes=5))
    with pytest.raises(ValueError, match="batch_size"):
        _validate_claim_options("worker", 0, timedelta(minutes=5))
    with pytest.raises(ValueError, match="stale_after"):
        _validate_claim_options("worker", 100, timedelta(0))


def test_transaction_retry_requires_positive_delay() -> None:
    from prodkit_storage.database.transactions import run_sync_transaction

    with pytest.raises(ValueError, match="base_delay_seconds"):
        run_sync_transaction(  # type: ignore[arg-type]
            None, lambda session: None, base_delay_seconds=0
        )


def test_stream_maxlen_validation() -> None:
    from prodkit_storage.redis.streams import _validate_maxlen

    with pytest.raises(ValueError, match="maxlen"):
        _validate_maxlen(0)
