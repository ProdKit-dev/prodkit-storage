# Validation report

Validated on 2026-08-07 against the `v0.3.0` operational-hardening pull-request source tree.

## Release-gate results

The latest exact PR head passed the repository's complete GitHub Actions test and security jobs.

### Reproducibility and static checks

- `uv.lock` was regenerated with `uv` and `uv lock` produces no diff.
- CI installs the complete dependency graph with `uv sync --all-extras --locked`.
- Ruff passed with the repository rule set.
- Strict mypy passed across 62 package source files.
- The package builds and installs as `prodkit-storage==0.3.0` under Python 3.12.

### PostgreSQL, PostGIS, Alembic, and schema safety

- PostgreSQL 18/PostGIS 3.6 service health passed.
- Privileged PostGIS/pgcrypto bootstrap completed outside routine Alembic migrations.
- Alembic generated the full offline upgrade SQL and upgraded a fresh database to
  `20260807_0002`.
- `alembic current`, `heads`, and `history` agree on one head.
- Sync and async `prodkit-storage schema-check` both report the expected revision as current.
- `alembic check` reports no metadata drift.
- Published Alembic revisions are checked for immutability; newly added revisions are
  subjected to the migration-safety linter.
- A one-step downgrade to `20260806_0001`, roll-forward to head, metadata-drift check,
  and sync/async schema-compatibility verification all passed.
- Live migration-helper tests passed for concurrent index creation, deferred CHECK
  validation, explicit constraint validation, and the prevalidated `SET NOT NULL` path.

### Data isolation, transactions, and backfills

- A real non-superuser/non-`BYPASSRLS` runtime role was tested against an RLS-protected
  table: tenant A and tenant B see only their own rows, and PostgreSQL rejects a
  cross-tenant write.
- Read-only transaction enforcement rejects writes at the database level.
- Append-only audit-role behavior permits the required audit insert/RETURNING path while
  denying payload/history reads.
- Stale outbox workers cannot complete events after lease reclamation.
- Joined-eager-load keyset pagination exercises SQLAlchemy `unique()` semantics.
- A live resumable-backfill test proves an interrupted batch and its checkpoint roll back
  together, while a subsequent run resumes from the last committed checkpoint without
  skipping rows.

### Redis and coordination

- Live Redis tests passed for atomic cache-tag invalidation, idempotency, token-owned
  locks, token-bucket rate limiting, and Streams publication.
- The dependency-failure smoke verified unavailable PostgreSQL and Redis report unhealthy
  promptly instead of hanging or returning a false healthy result.

### Backup, restore, and load smoke

- CI performed a real logical `pg_dump` -> scratch-database `pg_restore` using the
  PostgreSQL service container's matching client version.
- Source and restored row counts matched for the shared storage/version tables and the
  PostGIS spatial reference table.
- The concurrent DB/Redis saturation smoke completed 40/40 iterations at concurrency 8
  with zero errors. In the recorded validation run, database p95 was about 33 ms and
  Redis p95 about 20 ms, well below the deliberately generous CI regression thresholds.

### Tests and coverage

- **101 tests passed** in the complete unit + live integration suite.
- Statement/branch coverage was **81.40%**, above the configured 80% release threshold.
- The integration suite includes database behavior, infrastructure health, migration
  operations, resumable backfills, Redis behavior, and true RLS tenant isolation.

### Supply-chain checks

- `pip-audit` passed against the locked Python dependency graph.
- The runtime Docker image built successfully.
- Trivy HIGH/CRITICAL image scanning passed under the repository's reviewed ignore policy.
- An SPDX JSON SBOM was generated and uploaded successfully.
- GitHub Actions runs with repository `contents: read` permission during normal CI.

## What this validation proves

These checks provide strong evidence that the reusable storage foundation's code,
migrations, concurrency primitives, tenant-isolation integration, backup/restore smoke,
and operational guardrails behave as intended in the CI environment.

They do **not** prove that every consuming deployment is production-ready. Each product
and platform still owns its production data classification/retention rules, private
networking and TLS, secret rotation, total connection budgets, managed backup/PITR
retention, multi-zone failover, measured RPO/RTO, production-scale data/query profiles,
alert routing/on-call ownership, and compliance requirements.

The shipped load and failure exercises are regression smokes, not capacity benchmarks or
chaos-certification results. Provider-specific restore/failover drills and sustained
real-application dogfooding remain required evidence before a future `1.0.0` stability
claim.
