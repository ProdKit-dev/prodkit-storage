"""Declarative base and common model mixins."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from prodkit_storage.database.naming import NAMING_CONVENTION


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: MutableDict.as_mutable(JSONB)}


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


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


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, at: datetime | None = None) -> None:
        self.deleted_at = at or datetime.now(timezone.utc)

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
