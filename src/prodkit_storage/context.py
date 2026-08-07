"""Request and tenant context propagation using context variables."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    tenant_id: UUID | None = None
    actor_id: UUID | None = None
    request_id: str | None = None
    trace_id: str | None = None


_current_context: ContextVar[RequestContext] = ContextVar(
    "prodkit_storage_request_context",
    default=RequestContext(),
)


def get_request_context() -> RequestContext:
    return _current_context.get()


def get_tenant_id() -> UUID | None:
    return get_request_context().tenant_id


@contextmanager
def request_context(context: RequestContext) -> Iterator[RequestContext]:
    token: Token[RequestContext] = _current_context.set(context)
    try:
        yield context
    finally:
        _current_context.reset(token)


@contextmanager
def tenant_context(
    tenant_id: UUID,
    *,
    actor_id: UUID | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[RequestContext]:
    context = RequestContext(
        tenant_id=tenant_id,
        actor_id=actor_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    with request_context(context):
        yield context
