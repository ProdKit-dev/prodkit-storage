"""Resumable batched backfill orchestration for sync and async SQLAlchemy sessions.

The checkpoint callback and batch mutation run in the same database transaction,
so a failed batch rolls back both application changes and checkpoint advancement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

CursorT = TypeVar("CursorT")


@dataclass(frozen=True, slots=True)
class BackfillBatch(Generic[CursorT]):
    next_cursor: CursorT | None
    processed: int
    done: bool = False


@dataclass(frozen=True, slots=True)
class BackfillRun(Generic[CursorT]):
    batches: int
    processed: int
    checkpoint: CursorT | None
    completed: bool


SyncSessionFactory = Callable[[], Session]
SyncCheckpointLoader = Callable[[Session], CursorT | None]
SyncCheckpointSaver = Callable[[Session, CursorT | None], None]
SyncBatchProcessor = Callable[[Session, CursorT | None, int], BackfillBatch[CursorT]]

AsyncSessionFactory = Callable[[], AsyncSession]
AsyncCheckpointLoader = Callable[[AsyncSession], Awaitable[CursorT | None]]
AsyncCheckpointSaver = Callable[[AsyncSession, CursorT | None], Awaitable[None]]
AsyncBatchProcessor = Callable[
    [AsyncSession, CursorT | None, int],
    Awaitable[BackfillBatch[CursorT]],
]


def run_batched_backfill_sync(
    session_factory: SyncSessionFactory,
    *,
    load_checkpoint: SyncCheckpointLoader[CursorT],
    process_batch: SyncBatchProcessor[CursorT],
    save_checkpoint: SyncCheckpointSaver[CursorT],
    batch_size: int = 1_000,
    max_batches: int | None = None,
) -> BackfillRun[CursorT]:
    """Run bounded transactions until the backfill completes or the batch limit is hit."""

    _validate_options(batch_size, max_batches)
    batches = 0
    processed = 0
    checkpoint: CursorT | None = None
    completed = False

    while max_batches is None or batches < max_batches:
        with session_factory() as session, session.begin():
            checkpoint = load_checkpoint(session)
            batch = process_batch(session, checkpoint, batch_size)
            _validate_batch(batch, checkpoint)
            save_checkpoint(session, batch.next_cursor)
        batches += 1
        processed += batch.processed
        checkpoint = batch.next_cursor
        if batch.done:
            completed = True
            break

    return BackfillRun(
        batches=batches,
        processed=processed,
        checkpoint=checkpoint,
        completed=completed,
    )


async def run_batched_backfill_async(
    session_factory: AsyncSessionFactory,
    *,
    load_checkpoint: AsyncCheckpointLoader[CursorT],
    process_batch: AsyncBatchProcessor[CursorT],
    save_checkpoint: AsyncCheckpointSaver[CursorT],
    batch_size: int = 1_000,
    max_batches: int | None = None,
) -> BackfillRun[CursorT]:
    """Async equivalent of :func:`run_batched_backfill_sync`."""

    _validate_options(batch_size, max_batches)
    batches = 0
    processed = 0
    checkpoint: CursorT | None = None
    completed = False

    while max_batches is None or batches < max_batches:
        async with session_factory() as session, session.begin():
            checkpoint = await load_checkpoint(session)
            batch = await process_batch(session, checkpoint, batch_size)
            _validate_batch(batch, checkpoint)
            await save_checkpoint(session, batch.next_cursor)
        batches += 1
        processed += batch.processed
        checkpoint = batch.next_cursor
        if batch.done:
            completed = True
            break

    return BackfillRun(
        batches=batches,
        processed=processed,
        checkpoint=checkpoint,
        completed=completed,
    )


def _validate_options(batch_size: int, max_batches: int | None) -> None:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive when provided")


def _validate_batch(batch: BackfillBatch[CursorT], checkpoint: CursorT | None) -> None:
    if batch.processed < 0:
        raise ValueError("backfill batch processed count must not be negative")
    if not batch.done and batch.processed == 0 and batch.next_cursor == checkpoint:
        raise RuntimeError("backfill batch made no progress")


__all__ = [
    "BackfillBatch",
    "BackfillRun",
    "run_batched_backfill_async",
    "run_batched_backfill_sync",
]
