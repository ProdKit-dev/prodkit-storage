# Operational hardening

`v0.3.0` turns several production practices into executable repository gates rather
than leaving them as checklist prose.

## Migration safety

Published Alembic revisions are immutable. CI fails if an existing revision is
modified, deleted, renamed, or otherwise rewritten. A newly added revision is checked
with:

```bash
prodkit-storage migration-check path/to/new_revision.py
```

The linter inspects `upgrade()` and blocks common high-risk patterns:

- destructive `drop_*` operations;
- non-concurrent indexes on existing tables;
- `CREATE INDEX CONCURRENTLY` outside an Alembic `autocommit_block()`;
- immediately validated foreign-key/check constraints on existing tables;
- non-null columns added to existing tables without an expand/backfill plan;
- direct column-type rewrites.

`SET NOT NULL` and opaque `op.execute()` calls remain visible warnings requiring
manual lock/rewrite review.

If a risky operation is genuinely required, make the waiver explicit in the revision:

```python
migration_safety_allow = {"destructive-change"}
```

A waiver makes the decision auditable; it does not make the operation safe.

### Staged PostgreSQL migration helpers

`prodkit_storage.database` also exposes reviewed building blocks for the common safe
path:

- `create_index_concurrently()` — wraps the required Alembic autocommit block;
- `add_check_constraint_not_valid()` — installs a CHECK without scanning old rows;
- `add_foreign_key_not_valid()` — installs an FK without immediate old-row validation;
- `validate_constraint()` — validates a deferred constraint separately;
- `enforce_not_null()` — validates a temporary `IS NOT NULL` check before applying
  `SET NOT NULL`, avoiding a second full-table validation scan on supported PostgreSQL.

Destructive contract helpers are deliberately **not** provided: dropping an old column,
table, constraint, or index should remain visible in the revision so the safety linter
can require a reviewed waiver.

## Resumable backfills

`run_batched_backfill_sync()` and `run_batched_backfill_async()` execute one bounded
batch per transaction. The application supplies checkpoint load/save callbacks plus the
batch processor; the mutation and checkpoint advance happen in the same database
transaction.

That means an exception or process interruption rolls back both the current batch and
its checkpoint, while earlier batches remain committed and resumable. `max_batches`
lets a scheduler deliberately cap work per invocation.

The CI integration suite simulates interruption after a partially executed batch and
proves the batch rolls back, the prior checkpoint remains stable, and a later worker
resumes to completion without skipping rows.

The checkpoint must live in the **same transactional database** as the backfilled data
for the atomicity guarantee to hold. External checkpoint stores need their own delivery
and reconciliation design.

## Runtime schema compatibility

The package exposes an explicit schema contract:

```python
from prodkit_storage import (
    STORAGE_SCHEMA_COMPATIBILITY_VERSION,
    STORAGE_SCHEMA_HEAD,
    check_schema_compatibility_sync,
)
```

Deployments can fail readiness/release verification when the database revision is not
accepted by the running package. The CLI equivalent is:

```bash
prodkit-storage schema-check
prodkit-storage schema-check --async
```

When a future package can safely run against more than one Alembic revision, extend
`SchemaCompatibilityPolicy.compatible_revisions` deliberately rather than inferring
ordering from opaque revision strings.

## Tenant isolation

CI creates a real non-superuser/non-`BYPASSRLS` runtime role and RLS-protected table.
The integration test proves that tenant A and tenant B see only their own rows and
that PostgreSQL rejects a cross-tenant write through the runtime role. This complements
`verify_rls_sync`/`verify_rls_async`, which inspect deployed role/table configuration.

Applications still need equivalent tests for their own RLS policies and domain tables.

## Backup and restore verification

`ops/backup/verify_postgres_backup.py` performs a logical backup, restores it to a
scratch database, and compares user-table row counts between source and restore.

For a local PostgreSQL client matching the server version:

```bash
uv run python ops/backup/verify_postgres_backup.py \
  --database-url "$PRODKIT_STORAGE_DATABASE_URL"
```

CI uses the PostgreSQL/PostGIS service container's matching `pg_dump`/`pg_restore`
binaries so an older runner client cannot silently invalidate the exercise.

This is a logical-restore smoke test, not a replacement for managed-provider PITR,
WAL/archive verification, encryption validation, or measured RPO/RTO drills.

## Load and failure smoke tests

`ops/load/storage_smoke.py` executes concurrent PostgreSQL pool checkouts/queries and
Redis commands, reports p50/p95/p99 latency, and fails on errors or configured p95
thresholds:

```bash
uv run python ops/load/storage_smoke.py \
  --iterations 200 \
  --concurrency 20 \
  --database-p95-ms 500 \
  --redis-p95-ms 200
```

`ops/failure/dependency_failure_smoke.py` points short-timeout PostgreSQL and Redis
clients at deliberately unused local ports and verifies both health paths report a
visible failure promptly instead of hanging or incorrectly returning healthy.

CI intentionally uses generous latency thresholds to catch broken pooling/network
behavior, not to claim benchmark-grade performance. Real capacity and failure planning
must use production-representative query shapes, data volumes, network topology,
concurrency, failovers, and downstream dependencies.

## Dashboards, alerts, and runbooks

Operational starter assets are under `ops/` and `docs/runbooks/`:

- `ops/grafana/prodkit-storage-dashboard.json`;
- `ops/prometheus/prodkit-storage-alerts.yml`;
- `docs/runbooks/database.md`;
- `docs/runbooks/redis.md`;
- `docs/runbooks/outbox.md`;
- `ops/terraform/README.md`.

The Prometheus examples assume the default OpenTelemetry-to-Prometheus translation
strategy where dotted metric/attribute names are converted to underscores and type/unit
suffixes are added. If the collector/exporter uses another translation strategy, adapt
the queries before enabling alerts.

Alert thresholds are starting values, not universal SLOs. Tune them from observed
baselines and customer-impact objectives.

## What remains deployment-specific

The library cannot prove these properties by itself:

- provider multi-zone failover and measured RPO/RTO;
- production backup retention/PITR correctness;
- global connection budgets across every service/worker replica;
- organization-specific on-call/escalation ownership;
- real application data classification/retention/legal-hold policy;
- sustained beta/load evidence from production-like applications.

Treat those as application/platform acceptance gates rather than pretending a reusable
Python package can guarantee them.
