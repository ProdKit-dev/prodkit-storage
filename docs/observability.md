# Observability

Observability is disabled by default and is activated with the
`prodkit-storage[observability]` extra plus application-configured OpenTelemetry
SDK/exporters.

```dotenv
PRODKIT_STORAGE_OBSERVABILITY_ENABLED=true
PRODKIT_STORAGE_SERVICE_NAME=billing-api
PRODKIT_STORAGE_PROCESS_TYPE=app
PRODKIT_STORAGE_INSTANCE_ID=billing-api-7f5bc6c7d8-mk9t2
PRODKIT_STORAGE_OTEL_SERVICE_NAME=billing-api
```

## Signals

The package records or exposes:

- SQL query duration and failure counts;
- slow-query logs and transaction spans with request, trace, actor, tenant, and component context;
- transaction duration, outcome, and read-only intent;
- connection-pool events and size/checked-out/overflow samples;
- Redis command duration and failure counts;
- outbox pending/dead counts and oldest pending-event age;
- explicit transaction spans;
- official SQLAlchemy and Redis OpenTelemetry instrumentation when installed.

Request, trace, actor, and tenant identifiers are deliberately excluded from
metric labels to avoid unbounded cardinality; they remain available in traces
and correlated logs.

Query parameters are not logged by default. Additional SQL text/comment capture
is opt-in. Enable it only after reviewing the risk of credentials, tokens,
personal data, and regulated values appearing in statements or parameters.

## Application responsibilities

The application configures the tracer/meter provider, sampling, exporters,
resource attributes, collector authentication, retention, dashboards, SLOs,
and alert rules. Health probes alone are not an SLO.

Recommended alerts include:

- database availability and saturation;
- connection checkout time and pool exhaustion;
- statement timeouts, deadlocks, and lock waits;
- replica lag and backup freshness;
- Redis latency, memory, eviction, replication, and persistence failures;
- outbox backlog, oldest pending age, and dead events.
