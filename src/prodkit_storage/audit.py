"""Audit event creation helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.context import get_request_context
from prodkit_storage.models.audit import AuditEvent


def record_audit_event(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_type: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> AuditEvent:
    event = _build_event(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        before=before,
        after=after,
        metadata=metadata,
        source_ip=source_ip,
        user_agent=user_agent,
    )
    session.add(event)
    return event


def record_audit_event_async(
    session: AsyncSession,
    **kwargs: Any,
) -> AuditEvent:
    event = _build_event(**kwargs)
    session.add(event)
    return event


def _build_event(
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    actor_type: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
) -> AuditEvent:
    context = get_request_context()
    return AuditEvent(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        actor_type=actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
        source_ip=source_ip,
        user_agent=user_agent,
        before=before,
        after=after,
        metadata_=metadata or {},
    )
