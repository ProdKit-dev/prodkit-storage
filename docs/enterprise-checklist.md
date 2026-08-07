# Enterprise readiness checklist

The code foundation is only one part of production readiness.

## Data architecture

- [ ] Data classification, retention, deletion, export, and legal-hold policies are defined.
- [ ] Tenant isolation model and regional/data-residency requirements are approved.
- [ ] Primary keys, external IDs, uniqueness, soft deletion, and archival rules are consistent.
- [ ] High-growth tables have partitioning/archival plans before they become operational incidents.
- [ ] PostGIS SRIDs and accuracy expectations are explicit.

## Reliability

- [ ] Multi-zone PostgreSQL and Redis failover are configured and tested.
- [ ] RPO/RTO are documented and restore exercises meet them.
- [ ] Connection budgets include all services and emergency headroom.
- [ ] Replica-lag behavior and read-your-writes requirements are documented.
- [ ] Outbox consumers are idempotent and dead-letter events have an operator workflow.
- [ ] Cache stampede, Redis outage, and database overload behavior are load tested.

## Security

- [ ] Runtime, migrator, owner, support, and read-only database roles are separated.
- [ ] Runtime roles do not own RLS-protected tables and do not have `BYPASSRLS`.
- [ ] Network access is private and encrypted.
- [ ] Credentials are managed and rotated through a secret manager.
- [ ] Logs and audit snapshots redact credentials, tokens, payment data, and regulated fields.
- [ ] Dependency/container vulnerability scanning and patch SLAs exist.

## Delivery

- [ ] Migrations use expand/backfill/switch/enforce/contract.
- [ ] Large indexes and constraint validation avoid long blocking locks.
- [ ] Fresh install, supported upgrade paths, rollback/roll-forward, and metadata drift are tested in CI.
- [ ] Deployment jobs run migrations once with a dedicated role.
- [ ] Application versions expose schema compatibility and readiness.

## Observability and operations

- [ ] SLOs and alerts exist for database availability, latency, errors, saturation, replication, backups, and storage.
- [ ] Slow-query, lock, deadlock, vacuum, bloat, and transaction-age dashboards exist.
- [ ] Redis memory, eviction, persistence, replication, latency, and stream lag are monitored.
- [ ] Runbooks cover failover, credential rotation, migration failure, restore, RLS incident, and outbox backlog.
- [ ] On-call ownership and escalation paths are clear.

## Compliance

- [ ] Audit events are immutable enough for the applicable threat model.
- [ ] Administrative cross-tenant access is time-bounded, justified, and audited.
- [ ] Data subject access/deletion workflows include primary, replicas, caches, exports, and backups according to policy.
- [ ] Vendor and infrastructure controls match contractual requirements.
