"""Audit event creation helpers with classification and redaction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from prodkit_storage.context import get_request_context
from prodkit_storage.models.audit import AuditEvent
from prodkit_storage.security.audit import AuditPolicy, DEFAULT_AUDIT_POLICY


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
    policy: AuditPolicy | None = DEFAULT_AUDIT_POLICY,
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
        policy=policy,
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
    policy: AuditPolicy | None = DEFAULT_AUDIT_POLICY,
) -> AuditEvent:
    context = get_request_context()
    sanitize = policy.sanitize if policy is not None else _identity
    sanitized_before = sanitize(before) if before is not None else None
    sanitized_after = sanitize(after) if after is not None else None
    sanitized_metadata = sanitize(metadata or {})
    if not isinstance(sanitized_before, (dict, type(None))):
        raise TypeError("sanitized audit before payload must be an object or null")
    if not isinstance(sanitized_after, (dict, type(None))):
        raise TypeError("sanitized audit after payload must be an object or null")
    if not isinstance(sanitized_metadata, dict):
        raise TypeError("sanitized audit metadata must be an object")
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
        before=sanitized_before,
        after=sanitized_after,
        metadata_=sanitized_metadata,
    )


def _identity(value: Any) -> Any:
    return value


__all__ = ["record_audit_event", "record_audit_event_async"]
