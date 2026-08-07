"""Transaction-scoped PostgreSQL advisory locks."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.exceptions import LockNotAcquiredError

_LOCK_SQL = text("SELECT pg_try_advisory_xact_lock(:key)")


def advisory_lock_key(namespace: str, key: str) -> int:
    digest = hashlib.blake2b(f"{namespace}:{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def acquire_advisory_xact_lock(
    session: Session,
    namespace: str,
    key: str,
    *,
    required: bool = True,
) -> bool:
    acquired = bool(session.scalar(_LOCK_SQL, {"key": advisory_lock_key(namespace, key)}))
    if required and not acquired:
        raise LockNotAcquiredError(f"could not acquire PostgreSQL advisory lock {namespace}:{key}")
    return acquired


async def acquire_advisory_xact_lock_async(
    session: AsyncSession,
    namespace: str,
    key: str,
    *,
    required: bool = True,
) -> bool:
    acquired = bool(
        await session.scalar(_LOCK_SQL, {"key": advisory_lock_key(namespace, key)})
    )
    if required and not acquired:
        raise LockNotAcquiredError(f"could not acquire PostgreSQL advisory lock {namespace}:{key}")
    return acquired
