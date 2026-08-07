from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from prodkit_storage.audit import record_audit_event, record_audit_event_async
from prodkit_storage.context import (
    RequestContext,
    get_request_context,
    get_tenant_id,
    request_context,
    tenant_context,
)
from prodkit_storage.models import OutboxEvent
from prodkit_storage.outbox import (
    enqueue_outbox_event,
    mark_outbox_failed,
    mark_outbox_published,
)

TENANT_ID = UUID("19dd5df5-cf1f-461f-80fb-50b47be112f0")
ACTOR_ID = UUID("dd10f1a1-297b-4512-9ca2-540322f99bd0")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)


def test_request_and_tenant_context_restore_previous_value() -> None:
    assert get_tenant_id() is None
    outer = RequestContext(tenant_id=TENANT_ID, request_id="outer")
    with request_context(outer):
        assert get_request_context() == outer
        with tenant_context(ACTOR_ID, actor_id=TENANT_ID, request_id="inner") as inner:
            assert get_request_context() == inner
            assert get_tenant_id() == ACTOR_ID
        assert get_request_context() == outer
    assert get_request_context() == RequestContext()


def test_audit_helpers_capture_request_context() -> None:
    session = FakeSession()
    context = RequestContext(
        tenant_id=TENANT_ID,
        actor_id=ACTOR_ID,
        request_id="req-1",
        trace_id="trace-1",
    )
    with request_context(context):
        event = record_audit_event(
            session,  # type: ignore[arg-type]
            action="customer.updated",
            entity_type="customer",
            entity_id="cust-1",
            before={"name": "Before"},
            after={"name": "After"},
            metadata={"reason": "test"},
        )
        async_event = record_audit_event_async(
            session,  # type: ignore[arg-type]
            action="customer.read",
            entity_type="customer",
        )

    assert session.added == [event, async_event]
    assert event.tenant_id == TENANT_ID
    assert event.actor_id == ACTOR_ID
    assert event.request_id == "req-1"
    assert event.trace_id == "trace-1"
    assert event.metadata_ == {"reason": "test"}


def test_outbox_enqueue_and_terminal_state_helpers() -> None:
    session = FakeSession()
    available_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    with request_context(
        RequestContext(tenant_id=TENANT_ID, request_id="req-2", trace_id="trace-2")
    ):
        event = enqueue_outbox_event(
            session,  # type: ignore[arg-type]
            topic="orders",
            event_type="order.created",
            payload={"id": "order-1"},
            headers={"source": "api"},
            available_at=available_at,
        )

    assert session.added == [event]
    assert event.headers == {
        "source": "api",
        "request_id": "req-2",
        "trace_id": "trace-2",
    }
    assert event.available_at == available_at

    event.status = "processing"
    event.locked_at = available_at
    event.locked_by = "worker"
    mark_outbox_published(event, at=available_at)
    assert event.status == "published"
    assert event.published_at == available_at
    assert event.locked_at is None
    assert event.locked_by is None


def test_outbox_failure_retries_then_dead_letters() -> None:
    event = OutboxEvent(topic="orders", event_type="order.created", payload={})
    event.attempts = 2
    mark_outbox_failed(event, RuntimeError("temporary"), max_attempts=3, base_delay_seconds=1)
    assert event.status == "pending"
    assert event.available_at is not None
    assert event.last_error == "temporary"

    event.attempts = 3
    mark_outbox_failed(event, "permanent", max_attempts=3)
    assert event.status == "dead"
