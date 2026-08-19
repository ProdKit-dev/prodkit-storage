# Production operations

## Deployment topology

Prefer a managed PostgreSQL service with PostGIS support unless operating PostgreSQL is a core competency. Use private networking, TLS, encrypted disks, automated patching, multi-zone high availability, and a tested failover process.

Redis should also use private networking, authentication/ACLs, TLS where traffic leaves a trusted host boundary, replication/failover, and workload-appropriate persistence and eviction.

Provision approved PostgreSQL extensions in a privileged bootstrap/infrastructure workflow. Routine application migrations should connect as a dedicated migrator and, when owner separation is enabled, `SET ROLE` to the non-login schema owner. Runtime application roles must not receive extension-management privileges.

## PostgreSQL capability readiness

Every deployment that relies on optional PostgreSQL features should fail closed before serving dependent traffic. Use the capability CLI or equivalent Python API in deployment/readiness workflows:

```bash
uv run prodkit-storage capabilities \
  --require-extension postgis \
  --require-access-method gin \
  --require-text-search-config simple
```

A pgvector-backed consumer can additionally require:

```bash
uv run prodkit-storage capabilities \
  --require-extension vector \
  --require-access-method hnsw \
  --require-access-method ivfflat
```

Treat extension presence and extension version as infrastructure configuration. Storage reports capabilities; it does not execute runtime `CREATE EXTENSION`, `ALTER EXTENSION`, or automatic schema repair.

Maintain an approved inventory containing at least:

- PostgreSQL major/minor policy;
- PostGIS and pgvector versions where used;
- required access methods;
- required text-search configurations;
- owner/migrator/runtime role responsibilities;
- upgrade sequencing and rollback/failover expectations.

A capability check proves prerequisites are present. It does not prove workload suitability.

## Full-text and vector index operations

PostgreSQL FTS and pgvector indexes are production schema objects and should receive the same operational discipline as any other large index.

For GIN, HNSW, and IVFFlat changes:

- use deliberate migration revisions and concurrent creation where the PostgreSQL operation supports it;
- measure build time, CPU, memory, disk growth, temporary space, WAL generation, replica lag, and lock behavior on production-shaped data;
- inspect index validity/readiness after interrupted or failed builds;
- validate query plans with `EXPLAIN (ANALYZE, BUFFERS)` and realistic tenant/filter predicates;
- budget disk for old and new indexes during replacement/rebuild operations;
- define rollback/roll-forward procedures before production execution;
- do not let application runtime automatically create, drop, rebuild, or repair indexes.

For native full-text search, the application or specialized search package owns the authoritative text-search configuration, projection expression, language behavior, field weighting, ranking, highlighting, and query semantics.

For vector search, the application or specialized search package owns embedding models, dimensions, normalization, distance semantics, candidate policy, ranking/fusion, and acceptance targets. HNSW/IVFFlat parameters must be selected from measured recall/latency/build-cost evidence rather than copied from examples.

ANN filtering can materially affect recall and execution plans. Test representative tenant, authorization, and product filters together with the vector predicate rather than benchmarking unfiltered nearest-neighbor queries only.

## Stable reconciliation snapshots

Use explicit repeatable-read snapshot helpers for reconciliation or inspection flows that must observe one stable committed database state across a scan. The caller still chooses primary versus replica and read-only versus read/write behavior explicitly.

Long repeatable-read transactions retain old row versions and can increase vacuum pressure. Keep them bounded, monitor transaction age, and avoid treating a stable snapshot as a substitute for an application-specific checkpoint/restart strategy.

## Connection budgeting

Compute the worst case across every process:

```text
connections = replicas_of_each_process × (pool_size + max_overflow)
```

Include web processes, workers, schedulers, migration jobs, search/indexing workers, BI tools, support tools, monitoring, and emergency administrative headroom. Use PgBouncer when many short-lived application processes would otherwise exceed PostgreSQL connection capacity. Transaction pooling requires testing session-level features; this package uses transaction-local RLS settings and transaction-scoped advisory locks, which are compatible with transaction boundaries.

## Timeouts

The runtime sets per-client values for:

- connect timeout;
- command timeout;
- statement timeout;
- lock timeout;
- idle-in-transaction timeout.

Tune them by workload instead of globally increasing every limit. Long reports, backfills, and index/migration operations should use separate roles or clients with deliberately reviewed limits.

## Backups and recovery

A production plan needs:

- automated base backups;
- continuous WAL archiving and point-in-time recovery;
- cross-account or cross-region backup copies where required;
- retention matching legal and business requirements;
- encrypted backup storage and controlled restore credentials;
- routine restore tests, not only successful backup-job status;
- documented RPO and RTO with evidence from exercises.

PostgreSQL data checksums help detect corruption but are not a backup. Extension binaries and versions must also be available in the recovery environment before restoring databases that use extension-owned types such as PostGIS or pgvector.

## Replication and failover

Track replica lag in bytes and time. The application must tolerate replicas being unavailable and route critical reads to the primary. After failover, dispose/recreate pools so stale sockets and DNS state do not linger.

Heavy GIN/HNSW/IVFFlat builds can generate significant WAL and replica lag. Include those operations in migration capacity planning and failover risk assessment.

## Outbox operations

Each claimed outbox event receives a fresh `lock_token` and an optimistic `version`. A dispatcher that publishes outside the claim transaction should persist the `(event_id, lock_token)` claim and call the ownership-checked completion/failure helpers. If a stale worker wakes after a reclaim, treat `OutboxLeaseLostError` as an expected concurrency outcome; do not retry completion with the stale token.

Operationally:

- alert on oldest pending age, processing age, retry counts, and dead events;
- make downstream consumers idempotent because delivery remains at least once;
- replay dead events through an explicit operator workflow that records who initiated the replay and why;
- never "fix" a backlog by bulk-marking events published without verifying the external side effect;
- use a separate retention workflow for deleting old published/dead rows rather than granting routine runtime deletion.

## PostgreSQL monitoring

Monitor at least:

- availability and connection saturation;
- transaction rate, commit/rollback ratio, and long transactions;
- lock waits, deadlocks, statement timeouts, and serialization failures;
- slow queries and `pg_stat_statements` regressions;
- CPU, memory, disk latency, IOPS, free space, WAL volume, and checkpoint pressure;
- autovacuum progress, table/index bloat, dead tuples, and transaction ID age;
- replication lag and WAL retention;
- backup freshness and restore-test results;
- outbox pending age, processing leases, retries, and dead events;
- required extension/version drift and capability-readiness failures;
- invalid/not-ready indexes after migrations or interrupted builds;
- GIN/HNSW/IVFFlat size and build/rebuild behavior where used;
- FTS/vector query latency, query-plan regressions, candidate counts, and application-owned recall/relevance acceptance signals.

## Redis monitoring

Monitor:

- availability and command latency;
- connected clients, blocked clients, connection errors, and rejected connections;
- memory use, fragmentation, maxmemory headroom, evictions, and expired keys;
- replication offset/lag and failover events;
- AOF rewrite status, persistence errors, and last successful save;
- keyspace growth by workload and namespace;
- lock acquisition failures, idempotency conflicts, rate-limit script errors, and stream lag.

For locks and idempotency, `noeviction` is safer than silently deleting coordination state. Capacity exhaustion should alert and fail visibly.

## Security

- Never expose PostgreSQL or Redis directly to the public internet.
- Use least-privilege roles; runtime roles must not own tables or migrations.
- Do not grant extension creation/upgrade privileges to normal runtime roles.
- Keep the shared audit table append-only for the runtime role; grant audit reads to a separate approved role.
- Rotate credentials and support dual credentials during rotation.
- Never log full DSNs, Redis URLs, secrets, query parameters containing personal data, embeddings containing sensitive derived information, or unredacted audit snapshots.
- Review audit `before`/`after` fields for secrets and regulated data.
- Encrypt especially sensitive fields at the application layer with managed keys when database/disk encryption is insufficient.
- Patch PostgreSQL, PostGIS, pgvector, Redis, drivers, Python dependencies, and container images promptly.
- Scan migrations and dependencies in CI.

## Redis failure behavior

Define behavior per feature:

- Cache outage: bypass cache and protect PostgreSQL from a thundering herd.
- Rate-limit outage: choose fail-open or fail-closed per endpoint risk.
- Lock outage: usually fail closed rather than execute duplicate critical work.
- Idempotency outage: fail closed for payments/provisioning; do not risk duplicate side effects.
- Stream outage: keep events in the PostgreSQL outbox and retry later.

Cache tag invalidation is atomic on the Redis server. If Redis Cluster is introduced, validate that the chosen key/tag layout and Lua execution remain same-slot compatible before enabling this primitive unchanged.

## Release operations

ProdKit Storage releases are promoted from a temporary `release/vX.Y.Z` branch that must resolve exactly to current `main` and to the version in `pyproject.toml`.

The permanent release workflow:

1. verifies the release branch is exact current `main`;
2. verifies the locked dependency graph and reruns release static/test gates;
3. builds the Python wheel and sdist;
4. creates an exact-source archive;
5. generates and locally verifies `SHA256SUMS`;
6. creates/updates a draft GitHub Release and uploads assets;
7. verifies every remote asset's size and GitHub SHA-256 metadata;
8. publishes only after the tag resolves to the exact release SHA;
9. deletes the temporary release branch after success.

Published version tags are immutable. Never move a release tag to repair documentation or code; produce a new version instead. If a release branch becomes stale before publication, fast-forward/recreate it from the newly validated `main` rather than forcing publication of old source.

## Disaster recovery exercise

A credible exercise restores PostgreSQL to a selected timestamp, verifies required extension binaries/versions and migrations, restores or rebuilds Redis according to workload, reapplies/revalidates database roles and grants, starts applications against the recovered systems, validates tenant isolation and critical workflows, validates FTS/vector schema objects used by consumers, and measures actual RPO/RTO.

See [`postgresql-capabilities.md`](postgresql-capabilities.md), [`enterprise-checklist.md`](enterprise-checklist.md), and [`../VALIDATION.md`](../VALIDATION.md).
