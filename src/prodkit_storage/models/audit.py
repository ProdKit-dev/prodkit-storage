"""Append-only application audit log model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.database.base import Base, OptionalTenantMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, OptionalTenantMixin, Base):
    __tablename__ = "storage_audit_events"
    __table_args__ = (
        Index("ix_storage_audit_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_storage_audit_events_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_storage_audit_events_request_id", "request_id"),
        Index("ix_storage_audit_events_metadata_gin", "metadata", postgresql_using="gin"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    actor_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
