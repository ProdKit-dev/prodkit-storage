"""Database telemetry, pool metrics, tracing hooks, and slow-query logging."""

from __future__ import annotations

import logging
import threading
import time
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, event

from prodkit_storage.config import StorageSettings
from prodkit_storage.context import get_request_context

logger = logging.getLogger("prodkit_storage.sql")
_OBSERVED_ENGINES: weakref.WeakSet[Engine] = weakref.WeakSet()
_OBSERVER_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    size: int
    checked_in: int
    checked_out: int
    overflow: int


@dataclass(slots=True)
class _QueryObservation:
    started_at: float
    attributes: dict[str, Any]


class StorageTelemetry:
    """Optional OpenTelemetry metrics with a no-op fallback.

    The package depends only on the OpenTelemetry API. Exporters and SDK setup
    remain application responsibilities.
    """

    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.enabled = settings.observability_enabled
        self._query_duration: Any = None
        self._query_errors: Any = None
        self._transaction_duration: Any = None
        self._transaction_count: Any = None
        self._redis_duration: Any = None
        self._redis_errors: Any = None
        self._pool_events: Any = None
        self._pool_size: Any = None
        self._pool_checked_out: Any = None
        self._pool_overflow: Any = None
        self._outbox_pending: Any = None
        self._outbox_dead: Any = None
        self._outbox_oldest_age: Any = None
        self._tracer: Any = None
        if not self.enabled:
            return
        try:
            from opentelemetry import metrics, trace

            meter = metrics.get_meter(settings.telemetry_namespace)
            self._tracer = trace.get_tracer(settings.telemetry_namespace)
            prefix = settings.telemetry_namespace
            self._query_duration = meter.create_histogram(
                f"{prefix}.db.query.duration", unit="ms"
            )
            self._query_errors = meter.create_counter(f"{prefix}.db.query.errors")
            self._transaction_duration = meter.create_histogram(
                f"{prefix}.db.transaction.duration", unit="ms"
            )
            self._transaction_count = meter.create_counter(
                f"{prefix}.db.transactions"
            )
            self._redis_duration = meter.create_histogram(
                f"{prefix}.redis.command.duration", unit="ms"
            )
            self._redis_errors = meter.create_counter(
                f"{prefix}.redis.command.errors"
            )
            self._pool_events = meter.create_counter(f"{prefix}.db.pool.events")
            self._pool_size = meter.create_histogram(f"{prefix}.db.pool.size")
            self._pool_checked_out = meter.create_histogram(
                f"{prefix}.db.pool.checked_out"
            )
            self._pool_overflow = meter.create_histogram(
                f"{prefix}.db.pool.overflow"
            )
            self._outbox_pending = meter.create_histogram(
                f"{prefix}.outbox.pending"
            )
            self._outbox_dead = meter.create_histogram(f"{prefix}.outbox.dead")
            self._outbox_oldest_age = meter.create_histogram(
                f"{prefix}.outbox.oldest_pending_age", unit="s"
            )
        except ImportError:
            logger.warning(
                "observability enabled but OpenTelemetry API is unavailable",
                extra={"component": "observability"},
            )
            self.enabled = False

    def metric_attributes(self, **extra: Any) -> dict[str, Any]:
        """Return bounded-cardinality attributes suitable for metrics."""

        values: dict[str, Any] = {
            "service.name": self.settings.otel_service_name or self.settings.service_name,
            "process.type": self.settings.process_type,
        }
        if self.settings.instance_id:
            values["service.instance.id"] = self.settings.instance_id
        values.update({key: value for key, value in extra.items() if value is not None})
        return values

    def trace_attributes(self, **extra: Any) -> dict[str, Any]:
        """Return trace attributes, including request-scoped correlation values."""

        context = get_request_context()
        values = self.metric_attributes(**extra)
        if context.tenant_id is not None:
            values["tenant.id"] = str(context.tenant_id)
        if context.actor_id is not None:
            values["actor.id"] = str(context.actor_id)
        if context.request_id is not None:
            values["request.id"] = context.request_id
        if context.trace_id is not None:
            values["trace.id"] = context.trace_id
        return values

    def record_query(
        self,
        duration_ms: float,
        *,
        component: str,
        failed: bool = False,
    ) -> None:
        if not self.enabled:
            return
        attributes = self.metric_attributes(component=component)
        self._query_duration.record(duration_ms, attributes)
        if failed:
            self._query_errors.add(1, attributes)

    def record_transaction(
        self,
        duration_ms: float,
        *,
        component: str,
        outcome: str,
        read_only: bool,
    ) -> None:
        if not self.enabled:
            return
        attributes = self.metric_attributes(
            component=component,
            outcome=outcome,
            read_only=read_only,
        )
        self._transaction_duration.record(duration_ms, attributes)
        self._transaction_count.add(1, attributes)

    def record_redis(
        self,
        duration_ms: float,
        *,
        command: str,
        failed: bool = False,
    ) -> None:
        if not self.enabled:
            return
        attributes = self.metric_attributes(command=command)
        self._redis_duration.record(duration_ms, attributes)
        if failed:
            self._redis_errors.add(1, attributes)

    def record_pool_event(
        self,
        *,
        component: str,
        event_name: str,
        snapshot: PoolSnapshot | None = None,
    ) -> None:
        if not self.enabled:
            return
        attributes = self.metric_attributes(component=component, event=event_name)
        self._pool_events.add(1, attributes)
        if snapshot is not None:
            self._pool_size.record(snapshot.size, attributes)
            self._pool_checked_out.record(snapshot.checked_out, attributes)
            self._pool_overflow.record(snapshot.overflow, attributes)

    def record_outbox(
        self,
        *,
        pending: int,
        dead: int,
        oldest_pending_age_seconds: float | None,
    ) -> None:
        if not self.enabled:
            return
        attributes = self.metric_attributes()
        self._outbox_pending.record(pending, attributes)
        self._outbox_dead.record(dead, attributes)
        if oldest_pending_age_seconds is not None:
            self._outbox_oldest_age.record(oldest_pending_age_seconds, attributes)

    def start_span(self, name: str, **attributes: Any) -> Any:
        if not self.enabled or self._tracer is None:
            return _NullSpanContext()
        return self._tracer.start_as_current_span(
            name,
            attributes=self.trace_attributes(**attributes),
        )


class _NullSpanContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        del args


_TELEMETRY: dict[int, StorageTelemetry] = {}
_TELEMETRY_LOCK = threading.Lock()


def get_telemetry(settings: StorageSettings) -> StorageTelemetry:
    with _TELEMETRY_LOCK:
        telemetry = _TELEMETRY.get(id(settings))
        if telemetry is None:
            telemetry = StorageTelemetry(settings)
            _TELEMETRY[id(settings)] = telemetry
        return telemetry


def install_query_observer(
    engine: Engine,
    settings: StorageSettings,
    component: str = "database",
) -> None:
    with _OBSERVER_LOCK:
        if engine in _OBSERVED_ENGINES:
            return
        _OBSERVED_ENGINES.add(engine)
    telemetry = get_telemetry(settings)

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        del cursor, parameters, context, executemany
        attributes = {"component": component}
        if settings.otel_include_query_text:
            attributes["db.query.text"] = statement[:4000]
        conn.info.setdefault("prodkit_query_started", []).append(
            _QueryObservation(time.perf_counter(), attributes)
        )

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
        observation = _pop_query_observation(conn)
        if observation is None:
            return
        elapsed_ms = (time.perf_counter() - observation.started_at) * 1000
        telemetry.record_query(elapsed_ms, component=component)
        if elapsed_ms < settings.slow_query_threshold_ms:
            return
        request = get_request_context()
        extra = {
            "duration_ms": round(elapsed_ms, 3),
            "tenant_id": str(request.tenant_id) if request.tenant_id else None,
            "actor_id": str(request.actor_id) if request.actor_id else None,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "component": component,
            "statement": statement[:4000],
        }
        if settings.log_query_parameters:
            extra["parameters"] = parameters
        logger.warning("slow database query", extra=extra)

    @event.listens_for(engine, "handle_error")
    def handle_error(exception_context: Any) -> None:
        connection = exception_context.connection
        if connection is None:
            return
        observation = _pop_query_observation(connection)
        if observation is not None:
            elapsed_ms = (time.perf_counter() - observation.started_at) * 1000
            telemetry.record_query(elapsed_ms, component=component, failed=True)

    for event_name in ("connect", "checkout", "checkin", "invalidate"):
        event.listen(
            engine.pool,
            event_name,
            _pool_event_listener(engine, telemetry, component, event_name),
        )


def instrument_sqlalchemy_engines(
    engines: Sequence[Engine | None],
    settings: StorageSettings,
) -> bool:
    """Enable official OpenTelemetry SQLAlchemy instrumentation once per runtime."""

    if not settings.observability_enabled or not settings.otel_sqlalchemy_instrumentation:
        return False
    concrete = [engine for engine in engines if engine is not None]
    if not concrete:
        return False
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError:
        logger.warning("SQLAlchemy OpenTelemetry instrumentation is not installed")
        return False
    SQLAlchemyInstrumentor().instrument(
        engines=list(dict.fromkeys(concrete)),
        enable_commenter=settings.otel_sqlcommenter,
        enable_attribute_commenter=(
            settings.otel_sqlcommenter and settings.otel_include_query_text
        ),
    )
    return True


def instrument_sqlalchemy(engine: Engine | None, settings: StorageSettings) -> bool:
    """Backward-compatible single-engine instrumentation wrapper."""

    if engine is None:
        return False
    return instrument_sqlalchemy_engines((engine,), settings)


def pool_snapshot(engine: Engine) -> PoolSnapshot:
    pool = engine.pool
    return PoolSnapshot(
        size=_pool_value(pool, "size"),
        checked_in=_pool_value(pool, "checkedin"),
        checked_out=_pool_value(pool, "checkedout"),
        overflow=_pool_value(pool, "overflow"),
    )


def _pool_value(pool: Any, name: str) -> int:
    value = getattr(pool, name, 0)
    if callable(value):
        value = value()
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pool_event_listener(
    engine: Engine,
    telemetry: StorageTelemetry,
    component: str,
    event_name: str,
) -> Any:
    def listener(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        telemetry.record_pool_event(
            component=component,
            event_name=event_name,
            snapshot=pool_snapshot(engine),
        )

    return listener


def _pop_query_observation(connection: Any) -> _QueryObservation | None:
    stack = connection.info.get("prodkit_query_started", [])
    if not stack:
        return None
    observation = stack.pop()
    return observation if isinstance(observation, _QueryObservation) else None


def _discard_query_timer(connection: Any) -> None:
    """Backward-compatible timer cleanup helper."""

    stack = connection.info.get("prodkit_query_started", [])
    if stack:
        stack.pop()


__all__ = [
    "PoolSnapshot",
    "StorageTelemetry",
    "get_telemetry",
    "install_query_observer",
    "instrument_sqlalchemy",
    "instrument_sqlalchemy_engines",
    "pool_snapshot",
]
