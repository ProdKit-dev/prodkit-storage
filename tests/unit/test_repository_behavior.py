from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import String, select
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.database.base import Base, SoftDeleteMixin, UUIDPrimaryKeyMixin
from prodkit_storage.database.repository import AsyncRepository, SyncRepository
from prodkit_storage.exceptions import NotFoundError


class RepositoryCustomer(UUIDPrimaryKeyMixin, SoftDeleteMixin, Base):
    __tablename__ = "test_repository_customers"

    name: Mapped[str] = mapped_column(String(100))


class Result:
    rowcount = 2


class ScalarCollection:
    def __init__(self, values: list[Any]) -> None:
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class RepositorySession:
    def __init__(self) -> None:
        self.scalar_values: list[Any] = []
        self.scalars_values: list[list[Any]] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.statements: list[Any] = []

    def add(self, entity: Any) -> None:
        self.added.append(entity)

    def add_all(self, entities: list[Any]) -> None:
        self.added.extend(entities)

    def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_values.pop(0)

    def scalars(self, statement: Any) -> ScalarCollection:
        self.statements.append(statement)
        return ScalarCollection(self.scalars_values.pop(0))

    def delete(self, entity: Any) -> None:
        self.deleted.append(entity)

    def execute(self, statement: Any) -> Result:
        self.statements.append(statement)
        return Result()


class AsyncRepositorySession(RepositorySession):
    async def scalar(self, statement: Any) -> Any:
        return super().scalar(statement)

    async def scalars(self, statement: Any) -> ScalarCollection:
        return super().scalars(statement)

    async def delete(self, entity: Any) -> None:
        super().delete(entity)

    async def execute(self, statement: Any) -> Result:
        return super().execute(statement)


def customer(name: str = "Ada") -> RepositoryCustomer:
    return RepositoryCustomer(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name=name,
    )


def test_sync_repository_crud_and_soft_delete() -> None:
    session = RepositorySession()
    repository = SyncRepository(session, RepositoryCustomer)  # type: ignore[arg-type]
    entity = customer()
    assert repository.add(entity) is entity
    repository.add_all([customer("Grace")])
    assert len(session.added) == 2

    session.scalar_values = [entity, None, True]
    assert repository.get(entity.id) is entity
    with pytest.raises(NotFoundError):
        repository.require(UUID("00000000-0000-0000-0000-000000000099"))
    assert repository.exists(RepositoryCustomer.name == "Ada")

    session.scalars_values = [[entity]]
    assert repository.list() == [entity]
    session.scalar_values = [1]
    assert repository.count() == 1

    repository.delete(entity)
    assert entity.is_deleted
    repository.delete(entity, hard=True)
    assert session.deleted == [entity]
    assert repository.delete_where(RepositoryCustomer.name == "Ada") == 2


def test_sync_repository_for_update_and_explicit_statement() -> None:
    session = RepositorySession()
    entity = customer()
    session.scalar_values = [entity]
    session.scalars_values = [[entity]]
    repository = SyncRepository(session, RepositoryCustomer)  # type: ignore[arg-type]
    assert repository.require(entity.id, for_update=True) is entity
    assert repository.list(select(RepositoryCustomer)) == [entity]


@pytest.mark.asyncio
async def test_async_repository_crud_paths() -> None:
    session = AsyncRepositorySession()
    entity = customer()
    repository = AsyncRepository(session, RepositoryCustomer)  # type: ignore[arg-type]
    repository.add(entity)
    repository.add_all([customer("Grace")])

    session.scalar_values = [entity, True, 2]
    assert await repository.require(entity.id, for_update=True) is entity
    assert await repository.exists(RepositoryCustomer.name == "Ada")
    assert await repository.count(select(RepositoryCustomer)) == 2

    session.scalars_values = [[entity]]
    assert await repository.list() == [entity]
    await repository.delete(entity)
    assert entity.is_deleted
    await repository.delete(entity, hard=True)
    assert session.deleted == [entity]
    assert await repository.delete_where(RepositoryCustomer.name == "Ada") == 2
