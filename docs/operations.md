# Production operations

## Deployment topology

Prefer a managed PostgreSQL service with PostGIS support unless operating PostgreSQL is a core competency. Use private networking, TLS, encrypted disks, automated patching, multi-zone high availability, and a tested failover process.

Redis should also use private networking, authentication/ACLs, TLS where traffic leaves a trusted host boundary, replication/failover, and workload-appropriate persistence and eviction.

## Connection budgeting

Compute the worst case across every process:

```text
connections = replicas_of_each_process × (pool_size + max_overflow)
```

Include web processes, workers, schedulers, migration jobs, BI tools, support tools, monitoring, and emergency administrative headroom. Use PgBouncer when many short-lived application processes would otherwise exceed PostgreSQL connection capacity. Transaction pooling requires testing session-level features; this package uses transaction-local RLS settings and transaction-scoped advisory locks, which are compatible with transaction boundaries.

## Timeouts

The runtime sets per-client values for:

- connect timeout;
- command timeout;
- statement timeout;
- lock timeout;
- idle-in-transaction timeout.

Tune them by workload instead of globally increasing every limit. Long reports and migrations should use separate roles or clients with deliberately larger limits.

## Backups and recovery

A production plan needs:

- automated base backups;
- continuous WAL archiving and point-in-time recovery;
- cross-account or cross-region backup copies where required;
- retention matching legal and business requirements;
- encrypted backup storage and controlled restore credentials;
- routine restore tests, not only successful backup-job status;
- documented RPO and RTO with evidence from exercises.

PostgreSQL data checksums help detect corruption but are not a backup.

## Replication and failover

Track replica lag in bytes and time. The application must tolerate replicas being unavailable and route critical reads to the primary. After failover, dispose/recreate pools so stale sockets and DNS state do not linger.

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
- outbox pending age, processing leases, retries, and dead events.

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
- Rotate credentials and support dual credentials during rotation.
- Never log full DSNs, Redis URLs, secrets, query parameters containing personal data, or unredacted audit snapshots.
- Review audit `before`/`after` fields for secrets and regulated data.
- Encrypt especially sensitive fields at the application layer with managed keys when database/disk encryption is insufficient.
- Patch PostgreSQL, PostGIS, Redis, drivers, and container images promptly.
- Scan migrations and dependencies in CI.

## Redis failure behavior

Define behavior per feature:

- Cache outage: bypass cache and protect PostgreSQL from a thundering herd.
- Rate-limit outage: choose fail-open or fail-closed per endpoint risk.
- Lock outage: usually fail closed rather than execute duplicate critical work.
- Idempotency outage: fail closed for payments/provisioning; do not risk duplicate side effects.
- Stream outage: keep events in the PostgreSQL outbox and retry later.

## Disaster recovery exercise

A credible exercise restores PostgreSQL to a selected timestamp, verifies extensions and migrations, restores or rebuilds Redis according to workload, rotates credentials, starts applications against the recovered systems, validates tenant isolation and critical workflows, and measures actual RPO/RTO.
