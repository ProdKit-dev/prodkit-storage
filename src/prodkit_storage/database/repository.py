"""Composable typed repositories for SQLAlchemy 2.x.

Repositories provide common persistence mechanics without hiding SQLAlchemy.
Applications remain free to execute domain-specific statements directly.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from sqlalchemy import Select, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.base import ExecutableOption

from prodkit_storage.database.base import Base, SoftDeleteMixin
from prodkit_storage.database.filtering import FilterRegistry, FilterTerm
from prodkit_storage.database.pagination import (
    CursorCodec,
    CursorPage,
    OffsetPage,
    count_subquery,
    paginate_async,
    paginate_offset_async,
    paginate_offset_sync,
    paginate_sync,
)
from prodkit_storage.database.sorting import SortPlan
from prodkit_storage.exceptions import NotFoundError

ModelT = TypeVar("ModelT", bound=Base)
IdT = TypeVar("IdT")


@dataclass(frozen=True, slots=True)
class RowLock:
    nowait: bool = False
    skip_locked: bool = False
    read: bool = False
    key_share: bool = False

    def __post_init__(self) -> None:
        if self.nowait and self.skip_locked:
            raise ValueError("nowait and skip_locked cannot both be enabled")


class ReadRepositoryProtocol(Protocol[ModelT]):
    model: type[ModelT]

    def base_statement(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]: ...


class WriteRepositoryProtocol(ReadRepositoryProtocol[ModelT], Protocol):
    def add(self, entity: ModelT) -> ModelT: ...


class SyncRepository(Generic[ModelT, IdT]):
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def base_statement(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        statement = select(self.model)
        return self._apply_soft_delete(statement, include_deleted=include_deleted)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[ModelT]) -> None:
        self.session.add_all(list(entities))

    def create(
        self,
        entity: ModelT,
        *,
        flush: bool = False,
        refresh: bool = False,
    ) -> ModelT:
        self.add(entity)
        if flush or refresh:
            self.session.flush()
        if refresh:
            self.session.refresh(entity)
        return entity

    def update(
        self,
        entity: ModelT,
        *,
        values: Mapping[str, Any] | None = None,
        flush: bool = False,
        refresh: bool = False,
    ) -> ModelT:
        if values:
            for attribute, value in values.items():
                setattr(entity, attribute, value)
                try:
                    flag_modified(entity, attribute)
                except (KeyError, AttributeError):
                    pass
        self.session.add(entity)
        if flush or refresh:
            self.session.flush()
        if refresh:
            self.session.refresh(entity)
        return entity

    def get_one(self, statement: Select[tuple[ModelT]]) -> ModelT:
        return self.session.execute(statement).unique().scalar_one()

    def get_one_or_none(self, statement: Select[tuple[ModelT]]) -> ModelT | None:
        return self.session.execute(statement).unique().scalar_one_or_none()

    def get_all(self, statement: Select[tuple[ModelT]]) -> Sequence[ModelT]:
        return self.session.execute(statement).unique().scalars().all()

    def get(
        self,
        identity: IdT,
        *,
        options: Sequence[ExecutableOption] = (),
        for_update: bool = False,
        nowait: bool = False,
        skip_locked: bool = False,
        lock: RowLock | None = None,
        include_deleted: bool = False,
    ) -> ModelT | None:
        statement = self.base_statement(  # type: ignore[attr-defined]
            include_deleted=include_deleted
        ).where(
            self.model.id == identity
        )
        if options:
            statement = statement.options(*options)
        if lock is not None:
            if for_update or nowait or skip_locked:
                raise ValueError("lock cannot be combined with legacy row-lock arguments")
            statement = _apply_row_lock(statement, self.model, lock)
        elif for_update:
            statement = _apply_row_lock(
                statement,
                self.model,
                RowLock(nowait=nowait, skip_locked=skip_locked),
            )
        elif nowait or skip_locked:
            raise ValueError("nowait and skip_locked require for_update=True")
        return self.session.execute(statement).unique().scalar_one_or_none()

    def require(self, identity: IdT, **kwargs: Any) -> ModelT:
        entity = self.get(identity, **kwargs)
        if entity is None:
            raise NotFoundError(self.model.__name__, identity)
        return entity

    def list(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        options: Sequence[ExecutableOption] = (),
        include_deleted: bool = False,
    ) -> Sequence[ModelT]:
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        if options:
            query = query.options(*options)
        result = self.session.scalars(query)
        return _scalar_all(result)

    def stream(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        yield_per: int = 1_000,
        include_deleted: bool = False,
    ) -> Generator[ModelT, None, None]:
        if yield_per < 1:
            raise ValueError("yield_per must be positive")
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        result = self.session.scalars(query.execution_options(yield_per=yield_per))
        try:
            yield from result
        finally:
            close = getattr(result, "close", None)
            if callable(close):
                close()

    def count(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> int:
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        count = self.session.scalar(select(func.count()).select_from(count_subquery(query)))
        return int(count or 0)

    def exists(self, *criteria: Any, include_deleted: bool = False) -> bool:
        query = self.base_statement(include_deleted=include_deleted).where(*criteria)
        return bool(self.session.scalar(select(query.exists())))

    def delete(self, entity: ModelT, *, hard: bool = False) -> None:
        if isinstance(entity, SoftDeleteMixin) and not hard:
            entity.soft_delete()
            self.session.add(entity)
        else:
            self.session.delete(entity)

    def delete_where(self, *criteria: Any) -> int:
        result = self.session.execute(delete(self.model).where(*criteria))
        return _result_rowcount(result)

    def bulk_insert(self, values: Sequence[Mapping[str, Any]]) -> int:
        if not values:
            return 0
        result = self.session.execute(insert(self.model), list(values))
        return _result_rowcount(result, fallback=len(values))

    def bulk_update(self, values: Mapping[str, Any], *criteria: Any) -> int:
        if not values:
            return 0
        result = self.session.execute(update(self.model).where(*criteria).values(**values))
        return _result_rowcount(result)

    def paginate_cursor(
        self,
        statement: Select[tuple[ModelT]],
        *,
        sort: SortPlan,
        codec: CursorCodec,
        cursor: str | None = None,
        limit: int = 50,
        query_fingerprint: str | None = None,
    ) -> CursorPage[ModelT]:
        return paginate_sync(
            self.session,
            statement,
            sort=sort,
            codec=codec,
            cursor=cursor,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )

    def paginate_offset(
        self,
        statement: Select[tuple[ModelT]],
        *,
        page: int = 1,
        limit: int = 50,
        include_total: bool = True,
        count_statement: Select[Any] | None = None,
    ) -> OffsetPage[ModelT]:
        return paginate_offset_sync(
            self.session,
            statement,
            page=page,
            limit=limit,
            include_total=include_total,
            count_statement=count_statement,
        )

    def apply_filters(
        self,
        statement: Select[tuple[ModelT]],
        registry: FilterRegistry,
        terms: Iterable[FilterTerm],
    ) -> Select[tuple[ModelT]]:
        return registry.apply(statement, terms)  # type: ignore[return-value]

    def _apply_soft_delete(
        self,
        statement: Select[tuple[ModelT]],
        *,
        include_deleted: bool,
    ) -> Select[tuple[ModelT]]:
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            return statement.where(self.model.deleted_at.is_(None))
        return statement


class AsyncRepository(Generic[ModelT, IdT]):
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def base_statement(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        statement = select(self.model)
        return self._apply_soft_delete(statement, include_deleted=include_deleted)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[ModelT]) -> None:
        self.session.add_all(list(entities))

    async def create(
        self,
        entity: ModelT,
        *,
        flush: bool = False,
        refresh: bool = False,
    ) -> ModelT:
        self.add(entity)
        if flush or refresh:
            await self.session.flush()
        if refresh:
            await self.session.refresh(entity)
        return entity

    async def update(
        self,
        entity: ModelT,
        *,
        values: Mapping[str, Any] | None = None,
        flush: bool = False,
        refresh: bool = False,
    ) -> ModelT:
        if values:
            for attribute, value in values.items():
                setattr(entity, attribute, value)
                try:
                    flag_modified(entity, attribute)
                except (KeyError, AttributeError):
                    pass
        self.session.add(entity)
        if flush or refresh:
            await self.session.flush()
        if refresh:
            await self.session.refresh(entity)
        return entity

    async def get_one(self, statement: Select[tuple[ModelT]]) -> ModelT:
        result = await self.session.execute(statement)
        return result.unique().scalar_one()

    async def get_one_or_none(self, statement: Select[tuple[ModelT]]) -> ModelT | None:
        result = await self.session.execute(statement)
        return result.unique().scalar_one_or_none()

    async def get_all(self, statement: Select[tuple[ModelT]]) -> Sequence[ModelT]:
        result = await self.session.execute(statement)
        return result.unique().scalars().all()

    async def get(
        self,
        identity: IdT,
        *,
        options: Sequence[ExecutableOption] = (),
        for_update: bool = False,
        nowait: bool = False,
        skip_locked: bool = False,
        lock: RowLock | None = None,
        include_deleted: bool = False,
    ) -> ModelT | None:
        statement = self.base_statement(  # type: ignore[attr-defined]
            include_deleted=include_deleted
        ).where(
            self.model.id == identity
        )
        if options:
            statement = statement.options(*options)
        if lock is not None:
            if for_update or nowait or skip_locked:
                raise ValueError("lock cannot be combined with legacy row-lock arguments")
            statement = _apply_row_lock(statement, self.model, lock)
        elif for_update:
            statement = _apply_row_lock(
                statement,
                self.model,
                RowLock(nowait=nowait, skip_locked=skip_locked),
            )
        elif nowait or skip_locked:
            raise ValueError("nowait and skip_locked require for_update=True")
        result = await self.session.execute(statement)
        return result.unique().scalar_one_or_none()

    async def require(self, identity: IdT, **kwargs: Any) -> ModelT:
        entity = await self.get(identity, **kwargs)
        if entity is None:
            raise NotFoundError(self.model.__name__, identity)
        return entity

    async def list(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        options: Sequence[ExecutableOption] = (),
        include_deleted: bool = False,
    ) -> Sequence[ModelT]:
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        if options:
            query = query.options(*options)
        result = await self.session.scalars(query)
        return _scalar_all(result)

    async def stream(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        yield_per: int = 1_000,
        include_deleted: bool = False,
    ) -> AsyncGenerator[ModelT, None]:
        if yield_per < 1:
            raise ValueError("yield_per must be positive")
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        result = await self.session.stream_scalars(query.execution_options(yield_per=yield_per))
        try:
            async for entity in result:
                yield entity
        finally:
            await result.close()

    async def count(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> int:
        query = (
            self.base_statement(include_deleted=include_deleted)
            if statement is None
            else statement
        )
        if statement is not None:
            query = self._apply_soft_delete(query, include_deleted=include_deleted)
        count = await self.session.scalar(select(func.count()).select_from(count_subquery(query)))
        return int(count or 0)

    async def exists(self, *criteria: Any, include_deleted: bool = False) -> bool:
        query = self.base_statement(include_deleted=include_deleted).where(*criteria)
        return bool(await self.session.scalar(select(query.exists())))

    async def delete(self, entity: ModelT, *, hard: bool = False) -> None:
        if isinstance(entity, SoftDeleteMixin) and not hard:
            entity.soft_delete()
            self.session.add(entity)
        else:
            await self.session.delete(entity)

    async def delete_where(self, *criteria: Any) -> int:
        result = await self.session.execute(delete(self.model).where(*criteria))
        return _result_rowcount(result)

    async def bulk_insert(self, values: Sequence[Mapping[str, Any]]) -> int:
        if not values:
            return 0
        result = await self.session.execute(insert(self.model), list(values))
        return _result_rowcount(result, fallback=len(values))

    async def bulk_update(self, values: Mapping[str, Any], *criteria: Any) -> int:
        if not values:
            return 0
        result = await self.session.execute(update(self.model).where(*criteria).values(**values))
        return _result_rowcount(result)

    async def paginate_cursor(
        self,
        statement: Select[tuple[ModelT]],
        *,
        sort: SortPlan,
        codec: CursorCodec,
        cursor: str | None = None,
        limit: int = 50,
        query_fingerprint: str | None = None,
    ) -> CursorPage[ModelT]:
        return await paginate_async(
            self.session,
            statement,
            sort=sort,
            codec=codec,
            cursor=cursor,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )

    async def paginate_offset(
        self,
        statement: Select[tuple[ModelT]],
        *,
        page: int = 1,
        limit: int = 50,
        include_total: bool = True,
        count_statement: Select[Any] | None = None,
    ) -> OffsetPage[ModelT]:
        return await paginate_offset_async(
            self.session,
            statement,
            page=page,
            limit=limit,
            include_total=include_total,
            count_statement=count_statement,
        )

    def apply_filters(
        self,
        statement: Select[tuple[ModelT]],
        registry: FilterRegistry,
        terms: Iterable[FilterTerm],
    ) -> Select[tuple[ModelT]]:
        return registry.apply(statement, terms)  # type: ignore[return-value]

    def _apply_soft_delete(
        self,
        statement: Select[tuple[ModelT]],
        *,
        include_deleted: bool,
    ) -> Select[tuple[ModelT]]:
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            return statement.where(self.model.deleted_at.is_(None))
        return statement


def _apply_row_lock(
    statement: Select[tuple[ModelT]],
    model: type[ModelT],
    lock: RowLock,
) -> Select[tuple[ModelT]]:
    return statement.with_for_update(
        of=model,
        nowait=lock.nowait,
        skip_locked=lock.skip_locked,
        read=lock.read,
        key_share=lock.key_share,
    )


def _scalar_all(result: Any) -> Sequence[Any]:
    unique = getattr(result, "unique", None)
    if callable(unique):
        return unique().all()
    return result.all()


def _result_rowcount(result: Any, *, fallback: int = 0) -> int:
    rowcount = getattr(result, "rowcount", None)
    if rowcount is None:
        return fallback
    value = int(rowcount)
    return fallback if value < 0 else value


__all__ = [
    "AsyncRepository",
    "ReadRepositoryProtocol",
    "RowLock",
    "SyncRepository",
    "WriteRepositoryProtocol",
]
