"""Low-overhead slow-query logging hooks."""

from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Any

from sqlalchemy import Engine, event

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import get_request_context

logger = logging.getLogger("prodkit_storage.sql")
_OBSERVED_ENGINES: weakref.WeakSet[Engine] = weakref.WeakSet()
_OBSERVER_LOCK = threading.Lock()


def install_query_observer(engine: Engine, settings: StorageSettings) -> None:
    with _OBSERVER_LOCK:
        if engine in _OBSERVED_ENGINES:
            return
        _OBSERVED_ENGINES.add(engine)

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del cursor, statement, parameters, context, executemany
        conn.info.setdefault("prodkit_query_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del cursor, context, executemany
        stack = conn.info.get("prodkit_query_started", [])
        if not stack:
            return
        elapsed_ms = (time.perf_counter() - stack.pop()) * 1000
        if elapsed_ms < settings.slow_query_threshold_ms:
            return
        request = get_request_context()
        extra = {
            "duration_ms": round(elapsed_ms, 3),
            "tenant_id": str(request.tenant_id) if request.tenant_id else None,
            "request_id": request.request_id,
            "statement": statement[:4000],
        }
        if settings.log_query_parameters:
            extra["parameters"] = parameters
        logger.warning("slow database query", extra=extra)

    @event.listens_for(engine, "handle_error")
    def handle_error(exception_context: Any) -> None:
        connection = exception_context.connection
        if connection is not None:
            _discard_query_timer(connection)


def _discard_query_timer(connection: Any) -> None:
    stack = connection.info.get("prodkit_query_started", [])
    if stack:
        stack.pop()
