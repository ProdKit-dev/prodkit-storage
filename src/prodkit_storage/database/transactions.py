"""Retry helpers for transient PostgreSQL transaction failures."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from prodkit_storage.database.errors import is_retryable_database_error

T = TypeVar("T")


def run_sync_transaction(
    factory: sessionmaker[Session],
    operation: Callable[[Session], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.05,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if base_delay_seconds <= 0:
        raise ValueError("base_delay_seconds must be positive")
    for attempt in range(1, max_attempts + 1):
        try:
            with factory.begin() as session:
                return operation(session)
        except Exception as error:
            if attempt == max_attempts or not is_retryable_database_error(error):
                raise
            time.sleep(_delay(base_delay_seconds, attempt))
    raise AssertionError("unreachable")


async def run_async_transaction(
    factory: async_sessionmaker[AsyncSession],
    operation: Callable[[AsyncSession], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.05,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if base_delay_seconds <= 0:
        raise ValueError("base_delay_seconds must be positive")
    for attempt in range(1, max_attempts + 1):
        try:
            async with factory.begin() as session:
                return await operation(session)
        except Exception as error:
            if attempt == max_attempts or not is_retryable_database_error(error):
                raise
            await asyncio.sleep(_delay(base_delay_seconds, attempt))
    raise AssertionError("unreachable")


def _delay(base: float, attempt: int) -> float:
    cap = min(base * (2 ** (attempt - 1)), 2.0)
    return random.uniform(cap / 2, cap)  # noqa: S311
