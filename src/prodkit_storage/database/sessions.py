"""Static session intent types used by repository and integration APIs.

The branded ``NewType`` aliases are runtime no-ops. Database-level read-only
transactions remain the enforcement boundary; these types make intent visible
to type checkers, reviewers, and coding agents.
"""

from __future__ import annotations

from typing import NewType, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

SyncReadSession = NewType("SyncReadSession", Session)
SyncWriteSession = NewType("SyncWriteSession", Session)
AsyncReadSession = NewType("AsyncReadSession", AsyncSession)
AsyncWriteSession = NewType("AsyncWriteSession", AsyncSession)


def as_sync_read_session(session: Session) -> SyncReadSession:
    return cast(SyncReadSession, session)


def as_sync_write_session(session: Session) -> SyncWriteSession:
    return cast(SyncWriteSession, session)


def as_async_read_session(session: AsyncSession) -> AsyncReadSession:
    return cast(AsyncReadSession, session)


def as_async_write_session(session: AsyncSession) -> AsyncWriteSession:
    return cast(AsyncWriteSession, session)


__all__ = [
    "AsyncReadSession",
    "AsyncWriteSession",
    "SyncReadSession",
    "SyncWriteSession",
    "as_async_read_session",
    "as_async_write_session",
    "as_sync_read_session",
    "as_sync_write_session",
]
