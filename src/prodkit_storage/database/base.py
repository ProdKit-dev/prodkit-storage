"""Declarative base and common model mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, MetaData, String, func, inspect, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from prodkit_storage.database.naming import NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: MutableDict.as_mutable(JSONB)}

    def __repr__(self) -> str:
        """Return a persistence-safe representation without triggering lazy loads."""

        state = inspect(self)
        if state.identity is None:
            return f"{type(self).__name__}(identity=None)"
        identity: Any = state.identity[0] if len(state.identity) == 1 else state.identity
        return f"{type(self).__name__}(identity={identity!r})"


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    @classmethod
    def generate_id(cls) -> UUID:
        return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def touch(self, *, at: datetime | None = None) -> None:
        self.updated_at = at or datetime.now(UTC)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @hybrid_property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @is_deleted.inplace.expression
    @classmethod
    def _is_deleted_expression(cls) -> ColumnElement[bool]:
        return type_coerce(cls.deleted_at.is_not(None), Boolean)

    def soft_delete(self, *, at: datetime | None = None) -> None:
        self.deleted_at = at or datetime.now(UTC)

    def restore(self) -> None:
        self.deleted_at = None


class TenantMixin:
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)


class OptionalTenantMixin:
    tenant_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)


class OptimisticLockMixin:
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        return {"version_id_col": cls.version}


class ExternalIdMixin:
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


__all__ = [
    "Base",
    "ExternalIdMixin",
    "OptimisticLockMixin",
    "OptionalTenantMixin",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
