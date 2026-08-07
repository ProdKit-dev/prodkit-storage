"""Explicit sync and async unit-of-work implementations."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker


class SyncUnitOfWork:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.session: Session
        self._finished = False

    def __enter__(self) -> Self:
        self._finished = False
        self.session = self._factory()
        try:
            self.session.begin()
        except Exception:
            self.session.close()
            raise
        return self

    def commit(self) -> None:
        self.session.commit()
        self._finished = True

    def rollback(self) -> None:
        self.session.rollback()
        self._finished = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        try:
            if exc_type is not None or not self._finished:
                self.session.rollback()
        finally:
            self.session.close()


class AsyncUnitOfWork:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self.session: AsyncSession
        self._finished = False

    async def __aenter__(self) -> Self:
        self._finished = False
        self.session = self._factory()
        try:
            await self.session.begin()
        except Exception:
            await self.session.close()
            raise
        return self

    async def commit(self) -> None:
        await self.session.commit()
        self._finished = True

    async def rollback(self) -> None:
        await self.session.rollback()
        self._finished = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        try:
            if exc_type is not None or not self._finished:
                await self.session.rollback()
        finally:
            await self.session.close()
