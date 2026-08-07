"""PostgreSQL transaction-local tenant, actor, and request context."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import get_request_context
from prodkit_storage.exceptions import TenantContextError

_CONTEXT_SQL = text("SELECT set_config(:name, :value, true)")
_READ_ONLY_SQL = text("SET TRANSACTION READ ONLY")


class StorageSession(Session):
    """Session subclass used to install transaction-local PostgreSQL context."""


@event.listens_for(StorageSession, "after_begin")
def _apply_context_after_begin(
    session: Session,
    transaction: Any,
    connection: Connection,
) -> None:
    del transaction
    settings = session.info.get("storage_settings")
    if not isinstance(settings, StorageSettings):
        return

    # PostgreSQL requires transaction characteristics to be set before the
    # first query. Apply read-only mode before transaction-local RLS context.
    if session.info.get("read_only") is True:
        connection.execute(_READ_ONLY_SQL)

    if not settings.tenant_rls_enabled:
        return

    context = get_request_context()
    if settings.tenant_required and context.tenant_id is None:
        raise TenantContextError("a tenant context is required for this database transaction")

    values = (
        (settings.rls_tenant_setting, context.tenant_id),
        (settings.rls_actor_setting, context.actor_id),
        (settings.rls_request_setting, context.request_id),
    )
    for name, value in values:
        connection.execute(
            _CONTEXT_SQL,
            {"name": name, "value": "" if value is None else str(value)},
        )
