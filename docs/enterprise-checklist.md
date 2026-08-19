# Enterprise readiness checklist

The code foundation is only one part of production readiness. Check this list per deployment and per materially different workload; a green library CI run does not substitute for application/infrastructure acceptance.

## Data architecture

- [ ] Data classification, retention, deletion, export, and legal-hold policies are defined.
- [ ] Tenant isolation model and regional/data-residency requirements are approved.
- [ ] Primary keys, external IDs, uniqueness, soft deletion, and archival rules are consistent.
- [ ] High-growth tables have partitioning/archival plans before they become operational incidents.
- [ ] PostGIS SRIDs and accuracy expectations are explicit.
- [ ] Required PostgreSQL extensions and approved versions are documented per environment.
- [ ] Application-owned FTS language/configuration, searchable projection fields, and update semantics are explicit where native full-text search is used.
- [ ] Vector dimensions, distance semantics, embedding ownership/versioning, and sensitive-data treatment are explicit where pgvector is used.

## Capability and index readiness

- [ ] Deployment readiness fails closed when required extensions, access methods, or text-search configurations are unavailable.
- [ ] Privileged extension installation/upgrades are owned by infrastructure, not runtime roles or ordinary application migrations.
- [ ] GIN/HNSW/IVFFlat creation/rebuild procedures are tested on production-shaped data.
- [ ] Index build CPU, memory, disk, temporary-space, WAL, replica-lag, lock, and duration budgets are measured.
- [ ] Invalid/not-ready indexes are detectable after interrupted or failed migrations.
- [ ] Representative FTS/vector query plans are validated with real tenant/authorization/product filters.
- [ ] ANN workloads have measured recall/latency acceptance targets and tuned HNSW/IVFFlat parameters rather than copied defaults.
- [ ] Search-domain decisions—embeddings, ranking, fusion, highlighting, suggestions, query interpretation, and search-index lifecycle—remain owned by the consuming application or specialized search package.

## Reliability

- [ ] Multi-zone PostgreSQL and Redis failover are configured and tested.
- [ ] RPO/RTO are documented and restore exercises meet them.
- [ ] Recovery environments can restore databases that depend on approved PostGIS/pgvector extension versions.
- [ ] Connection budgets include all services, migration/indexing jobs, and emergency headroom.
- [ ] Replica-lag behavior and read-your-writes requirements are documented.
- [ ] Long repeatable-read reconciliation snapshots are bounded and monitored for vacuum/transaction-age impact.
- [ ] Outbox consumers are idempotent and dead-letter events have an operator workflow.
- [ ] Cache stampede, Redis outage, and database overload behavior are load tested.
- [ ] Heavy index builds/rebuilds are included in WAL, replication, failover, and capacity planning.

## Security

- [ ] Runtime, migrator, owner, support, and read-only database roles are separated.
- [ ] Runtime roles do not own RLS-protected tables and do not have `BYPASSRLS`.
- [ ] Runtime roles cannot install or upgrade privileged PostgreSQL extensions.
- [ ] Network access is private and encrypted.
- [ ] Credentials are managed and rotated through a secret manager.
- [ ] Logs and audit snapshots redact credentials, tokens, payment data, regulated fields, and sensitive query/vector payloads.
- [ ] Dependency/container vulnerability scanning and patch SLAs exist for PostgreSQL, PostGIS, pgvector, Redis, drivers, Python packages, and runtime images.

## Delivery

- [ ] Migrations use expand/backfill/switch/enforce/contract where appropriate.
- [ ] Large indexes and constraint validation avoid long blocking locks.
- [ ] Fresh install, supported upgrade paths, rollback/roll-forward, and metadata drift are tested in CI.
- [ ] Deployment jobs run migrations once with a dedicated role.
- [ ] Application versions expose schema compatibility and readiness.
- [ ] PostgreSQL capability checks run before workloads that require optional extensions/features are enabled.
- [ ] Failed concurrent index operations have an explicit inspect/recover/rebuild procedure rather than runtime auto-repair.
- [ ] Consuming applications pin immutable ProdKit Storage release tags or exact versions, never floating `main`.

## Release and supply chain

- [ ] The intended release branch resolves exactly to validated `main` before publication.
- [ ] Release version metadata, changelog, README, architecture, roadmap, validation evidence, and consumer docs agree.
- [ ] Wheel, sdist, exact-source archive, and `SHA256SUMS` are produced from the exact release source.
- [ ] Published release assets are verified against remote size/SHA-256 metadata.
- [ ] Published version tags are treated as immutable and are never moved to repair released content.
- [ ] Temporary release/development branches are deleted only after their changes are merged and release evidence is verified.

## Observability and operations

- [ ] SLOs and alerts exist for database availability, latency, errors, saturation, replication, backups, and storage.
- [ ] Slow-query, lock, deadlock, vacuum, bloat, and transaction-age dashboards exist.
- [ ] Required extension/version drift and PostgreSQL capability-readiness failures are monitored.
- [ ] FTS/vector query latency, candidate counts, index health, and application-owned relevance/recall signals are monitored where applicable.
- [ ] Redis memory, eviction, persistence, replication, latency, and stream lag are monitored.
- [ ] Runbooks cover failover, credential rotation, migration failure, restore, RLS incident, outbox backlog, extension readiness failure, and failed large-index builds.
- [ ] On-call ownership and escalation paths are clear.

## Compliance

- [ ] Audit events are immutable enough for the applicable threat model.
- [ ] Administrative cross-tenant access is time-bounded, justified, and audited.
- [ ] Data subject access/deletion workflows include primary, replicas, caches, projections/vector data, exports, and backups according to policy.
- [ ] Derived embeddings/projections containing personal or regulated information follow approved retention/deletion controls.
- [ ] Vendor and infrastructure controls match contractual requirements.
