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

## Prometheus and Grafana starter assets

`v0.3.0` includes:

- `ops/prometheus/prodkit-storage-alerts.yml`;
- `ops/grafana/prodkit-storage-dashboard.json`;
- database, Redis, and outbox incident runbooks under `docs/runbooks/`.

The templates assume the default OpenTelemetry-to-Prometheus translation behavior:
dotted OpenTelemetry names/attributes become underscore-delimited Prometheus names,
unit suffixes are added, and counters receive `_total`. OpenTelemetry exporters can
use other translation strategies, so verify the emitted metric names before enabling
alerts in production.

The dashboard intentionally focuses on measurements that have unambiguous Prometheus
semantics: database/Redis latency histograms, error counters, and transaction outcomes.
Outbox backlog snapshots should be surfaced as current-value gauges by the consuming
application/collector before creating threshold alerts; do not derive a "current"
backlog from a cumulative histogram.

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

Tune alert thresholds from observed baselines and customer-impact objectives rather
than treating the repository examples as universal SLOs.
