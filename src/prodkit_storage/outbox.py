"""Transactional outbox enqueue, claim, and completion operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.context import get_request_context
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
        event.attempts += 1
    await session.flush()
    return events


def mark_outbox_published(event: OutboxEvent, *, at: datetime | None = None) -> None:
    event.status = "published"
    event.published_at = at or datetime.now(timezone.utc)
    event.locked_at = None
    event.locked_by = None
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
