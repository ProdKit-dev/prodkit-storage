from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from prodkit_storage.models import OutboxEvent
from prodkit_storage.outbox import claim_outbox_events, claim_outbox_events_async


class ScalarResult:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events

    def all(self) -> list[OutboxEvent]:
        return self.events


class ClaimSession:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.events = events
        self.statement: Any = None
        self.flushed = False

    def scalars(self, statement: Any) -> ScalarResult:
        self.statement = statement
        return ScalarResult(self.events)

    def flush(self) -> None:
        self.flushed = True


class AsyncClaimSession(ClaimSession):
    async def scalars(self, statement: Any) -> ScalarResult:
        return super().scalars(statement)

    async def flush(self) -> None:
        super().flush()


def pending_event() -> OutboxEvent:
    return OutboxEvent(
        topic="orders",
        event_type="order.created",
        payload={},
        status="pending",
        attempts=0,
        available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )


def test_sync_claim_marks_processing_and_flushes() -> None:
    event = pending_event()
    session = ClaimSession([event])
    claimed = claim_outbox_events(
        session,  # type: ignore[arg-type]
        worker_id="worker-1",
        batch_size=10,
        stale_after=timedelta(minutes=1),
    )
    assert claimed == [event]
    assert event.status == "processing"
    assert event.locked_by == "worker-1"
    assert event.locked_at is not None
    assert event.attempts == 1
    assert session.flushed


@pytest.mark.asyncio
async def test_async_claim_marks_processing_and_flushes() -> None:
    event = pending_event()
    session = AsyncClaimSession([event])
    claimed = await claim_outbox_events_async(
        session,  # type: ignore[arg-type]
        worker_id="worker-async",
    )
    assert claimed == [event]
    assert event.status == "processing"
    assert event.locked_by == "worker-async"
    assert event.attempts == 1
    assert session.flushed
