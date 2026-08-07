"""Transactional outbox enqueue, claim, and completion operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import get_request_context
from prodkit_storage.database.observability import get_telemetry
from prodkit_storage.exceptions import OutboxLeaseLostError
from prodkit_storage.models.outbox import OutboxEvent


def enqueue_outbox_event(
    session: Session | AsyncSession,
    *,
    topic: str,
    event_type: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    available_at: datetime | None = None,
) -> OutboxEvent:
    context = get_request_context()
    merged_headers = dict(headers or {})
    if context.request_id:
        merged_headers.setdefault("request_id", context.request_id)
    if context.trace_id:
        merged_headers.setdefault("trace_id", context.trace_id)
    event = OutboxEvent(
        tenant_id=context.tenant_id,
        topic=topic,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        headers=merged_headers,
        available_at=available_at or datetime.now(timezone.utc),
    )
    session.add(event)
    return event


def claim_outbox_events(
    session: Session,
    *,
    worker_id: str,
    batch_size: int = 100,
    stale_after: timedelta = timedelta(minutes=5),
) -> list[OutboxEvent]:
    _validate_claim_options(worker_id, batch_size, stale_after)
    now = datetime.now(timezone.utc)
    stale_before = now - stale_after
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.available_at <= now,
            (OutboxEvent.status == "pending")
            | (
                (OutboxEvent.status == "processing")
                & ((OutboxEvent.locked_at.is_(None)) | (OutboxEvent.locked_at < stale_before))
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    events = list(session.scalars(statement).all())
    for event in events:
        event.status = "processing"
        event.locked_at = now
        event.locked_by = worker_id
        event.lock_token = uuid4()
        event.attempts += 1
    session.flush()
    return events


async def claim_outbox_events_async(
    session: AsyncSession,
    *,
    worker_id: str,
    batch_size: int = 100,
    stale_after: timedelta = timedelta(minutes=5),
) -> list[OutboxEvent]:
    _validate_claim_options(worker_id, batch_size, stale_after)
    now = datetime.now(timezone.utc)
    stale_before = now - stale_after
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.available_at <= now,
            (OutboxEvent.status == "pending")
            | (
                (OutboxEvent.status == "processing")
                & ((OutboxEvent.locked_at.is_(None)) | (OutboxEvent.locked_at < stale_before))
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    result = await session.scalars(statement)
    events = list(result.all())
    for event in events:
        event.status = "processing"
        event.locked_at = now
        event.locked_by = worker_id
        event.lock_token = uuid4()
        event.attempts += 1
    await session.flush()
    return events


def complete_outbox_event(
    session: Session,
    *,
    event_id: UUID,
    lock_token: UUID,
    at: datetime | None = None,
) -> None:
    """Mark an event published only while the caller still owns its lease."""

    published_at = at or datetime.now(timezone.utc)
    result = session.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.status == "processing",
            OutboxEvent.lock_token == lock_token,
        )
        .values(
            status="published",
            published_at=published_at,
            locked_at=None,
            locked_by=None,
            lock_token=None,
            last_error=None,
            version=OutboxEvent.version + 1,
        )
    )
    if _rowcount(result) != 1:
        raise OutboxLeaseLostError(f"outbox event {event_id} lease is no longer owned")


async def complete_outbox_event_async(
    session: AsyncSession,
    *,
    event_id: UUID,
    lock_token: UUID,
    at: datetime | None = None,
) -> None:
    published_at = at or datetime.now(timezone.utc)
    result = await session.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.status == "processing",
            OutboxEvent.lock_token == lock_token,
        )
        .values(
            status="published",
            published_at=published_at,
            locked_at=None,
            locked_by=None,
            lock_token=None,
            last_error=None,
            version=OutboxEvent.version + 1,
        )
    )
    if _rowcount(result) != 1:
        raise OutboxLeaseLostError(f"outbox event {event_id} lease is no longer owned")


def fail_outbox_event(
    session: Session,
    *,
    event_id: UUID,
    lock_token: UUID,
    error: BaseException | str,
    max_attempts: int = 10,
    base_delay_seconds: int = 5,
) -> OutboxEvent:
    """Retry/dead-letter an event after proving the current lease is still owned."""

    event = session.scalar(
        select(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.status == "processing",
            OutboxEvent.lock_token == lock_token,
        )
        .with_for_update()
    )
    if event is None:
        raise OutboxLeaseLostError(f"outbox event {event_id} lease is no longer owned")
    mark_outbox_failed(
        event,
        error,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
    )
    session.flush()
    return event


async def fail_outbox_event_async(
    session: AsyncSession,
    *,
    event_id: UUID,
    lock_token: UUID,
    error: BaseException | str,
    max_attempts: int = 10,
    base_delay_seconds: int = 5,
) -> OutboxEvent:
    event = await session.scalar(
        select(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.status == "processing",
            OutboxEvent.lock_token == lock_token,
        )
        .with_for_update()
    )
    if event is None:
        raise OutboxLeaseLostError(f"outbox event {event_id} lease is no longer owned")
    mark_outbox_failed(
        event,
        error,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
    )
    await session.flush()
    return event


def mark_outbox_published(event: OutboxEvent, *, at: datetime | None = None) -> None:
    """Mutate a claimed ORM event to published state.

    Prefer :func:`complete_outbox_event` for workers that publish outside the
    claim transaction. The model's optimistic version still protects this
    legacy helper from stale ORM writes after a reclaim.
    """

    event.status = "published"
    event.published_at = at or datetime.now(timezone.utc)
    event.locked_at = None
    event.locked_by = None
    event.lock_token = None
    event.last_error = None


def mark_outbox_failed(
    event: OutboxEvent,
    error: BaseException | str,
    *,
    max_attempts: int = 10,
    base_delay_seconds: int = 5,
) -> None:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if base_delay_seconds <= 0:
        raise ValueError("base_delay_seconds must be positive")
    event.last_error = str(error)[:8000]
    event.locked_at = None
    event.locked_by = None
    event.lock_token = None
    if event.attempts >= max_attempts:
        event.status = "dead"
        return
    delay = min(base_delay_seconds * (2 ** max(event.attempts - 1, 0)), 3600)
    event.status = "pending"
    event.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)


def _validate_claim_options(
    worker_id: str,
    batch_size: int,
    stale_after: timedelta,
) -> None:
    if not worker_id.strip():
        raise ValueError("worker_id must not be empty")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")


def _rowcount(result: Any) -> int:
    value = getattr(result, "rowcount", None)
    return int(value) if value is not None and int(value) >= 0 else 0


@dataclass(frozen=True, slots=True)
class OutboxMetrics:
    pending: int
    processing: int
    published: int
    dead: int
    oldest_pending_age_seconds: float | None


def get_outbox_metrics(session: Session) -> OutboxMetrics:
    now = datetime.now(timezone.utc)
    counts = dict(
        session.execute(
            select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
        ).all()
    )
    oldest = session.scalar(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
    )
    metrics = _build_outbox_metrics(counts, oldest, now)
    settings = session.info.get("storage_settings")
    if isinstance(settings, StorageSettings):
        get_telemetry(settings).record_outbox(
            pending=metrics.pending,
            dead=metrics.dead,
            oldest_pending_age_seconds=metrics.oldest_pending_age_seconds,
        )
    return metrics


async def get_outbox_metrics_async(session: AsyncSession) -> OutboxMetrics:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
    )
    counts = dict(result.all())
    oldest = await session.scalar(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
    )
    metrics = _build_outbox_metrics(counts, oldest, now)
    settings = session.sync_session.info.get("storage_settings")
    if isinstance(settings, StorageSettings):
        get_telemetry(settings).record_outbox(
            pending=metrics.pending,
            dead=metrics.dead,
            oldest_pending_age_seconds=metrics.oldest_pending_age_seconds,
        )
    return metrics


def _build_outbox_metrics(
    counts: dict[str, int],
    oldest: datetime | None,
    now: datetime,
) -> OutboxMetrics:
    age = max((now - oldest).total_seconds(), 0.0) if oldest is not None else None
    return OutboxMetrics(
        pending=int(counts.get("pending", 0)),
        processing=int(counts.get("processing", 0)),
        published=int(counts.get("published", 0)),
        dead=int(counts.get("dead", 0)),
        oldest_pending_age_seconds=age,
    )


__all__ = [
    "OutboxMetrics",
    "claim_outbox_events",
    "claim_outbox_events_async",
    "complete_outbox_event",
    "complete_outbox_event_async",
    "enqueue_outbox_event",
    "fail_outbox_event",
    "fail_outbox_event_async",
    "get_outbox_metrics",
    "get_outbox_metrics_async",
    "mark_outbox_failed",
    "mark_outbox_published",
]
