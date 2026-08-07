"""Typed generic repositories for SQLAlchemy 2.x."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.database.base import Base, SoftDeleteMixin
from prodkit_storage.exceptions import NotFoundError

ModelT = TypeVar("ModelT", bound=Base)
IdT = TypeVar("IdT")


class SyncRepository(Generic[ModelT, IdT]):
    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[ModelT]) -> None:
        self.session.add_all(list(entities))

    def get(
        self,
        identity: IdT,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ModelT | None:
        statement = select(self.model).where(  # type: ignore[attr-defined]
            self.model.id == identity
        )
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            statement = statement.where(self.model.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(
        self,
        identity: IdT,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ModelT:
        entity = self.get(
            identity,
            for_update=for_update,
            include_deleted=include_deleted,
        )
        if entity is None:
            raise NotFoundError(self.model.__name__, identity)
        return entity

    def list(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> Sequence[ModelT]:
        query = select(self.model) if statement is None else statement
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        return self.session.scalars(query).all()

    def count(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> int:
        query = select(self.model) if statement is None else statement
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        return int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)

    def exists(self, *criteria: Any, include_deleted: bool = False) -> bool:
        query = select(self.model).where(*criteria)
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        return bool(self.session.scalar(select(query.exists())))

    def delete(self, entity: ModelT, *, hard: bool = False) -> None:
        if isinstance(entity, SoftDeleteMixin) and not hard:
            entity.soft_delete()
        else:
            self.session.delete(entity)

    def delete_where(self, *criteria: Any) -> int:
        result = self.session.execute(delete(self.model).where(*criteria))
        return int(result.rowcount or 0)


class AsyncRepository(Generic[ModelT, IdT]):
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    def add_all(self, entities: Iterable[ModelT]) -> None:
        self.session.add_all(list(entities))

    async def get(
        self,
        identity: IdT,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ModelT | None:
        statement = select(self.model).where(  # type: ignore[attr-defined]
            self.model.id == identity
        )
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            statement = statement.where(self.model.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def require(
        self,
        identity: IdT,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ModelT:
        entity = await self.get(
            identity,
            for_update=for_update,
            include_deleted=include_deleted,
        )
        if entity is None:
            raise NotFoundError(self.model.__name__, identity)
        return entity

    async def list(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> Sequence[ModelT]:
        query = select(self.model) if statement is None else statement
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        result = await self.session.scalars(query)
        return result.all()

    async def count(
        self,
        statement: Select[tuple[ModelT]] | None = None,
        *,
        include_deleted: bool = False,
    ) -> int:
        query = select(self.model) if statement is None else statement
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        count = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        return int(count or 0)

    async def exists(self, *criteria: Any, include_deleted: bool = False) -> bool:
        query = select(self.model).where(*criteria)
        if not include_deleted and issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.deleted_at.is_(None))
        return bool(await self.session.scalar(select(query.exists())))

    async def delete(self, entity: ModelT, *, hard: bool = False) -> None:
        if isinstance(entity, SoftDeleteMixin) and not hard:
            entity.soft_delete()
        else:
            await self.session.delete(entity)

    async def delete_where(self, *criteria: Any) -> int:
        result = await self.session.execute(delete(self.model).where(*criteria))
        return int(result.rowcount or 0)
