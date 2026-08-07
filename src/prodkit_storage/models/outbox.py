"""Transactional outbox model."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.database.base import (
    Base,
    OptimisticLockMixin,
    OptionalTenantMixin,
    UUIDPrimaryKeyMixin,
)


class OutboxEvent(
    UUIDPrimaryKeyMixin,
    OptionalTenantMixin,
    OptimisticLockMixin,
    Base,
):
    __tablename__ = "storage_outbox_events"
    __table_args__ = (
        Index(
            "ix_storage_outbox_events_dispatch",
            "status",
            "available_at",
            "created_at",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
        Index("ix_storage_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_storage_outbox_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_storage_outbox_events_payload_gin", "payload", postgresql_using="gin"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'published', 'dead')",
            name="status",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "(status = 'processing' AND lock_token IS NOT NULL) "
            "OR (status <> 'processing' AND lock_token IS NULL)",
            name="processing_has_lock_token",
        ),
    )

    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lock_token: Mapped[UUID | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
