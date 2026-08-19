# Validation report

Validated on 2026-08-19 for the `v0.4.0` release candidate and permanent release-hardening source.

## Release-gate results

The exact product candidate and the subsequent release-hardening pull request both passed the repository's complete permanent GitHub Actions `test` and `security` jobs. The final hardening validation run was `32210516297`.

### Reproducibility and static checks

- `uv.lock` is current and CI verifies it before installation.
- CI installs the complete dependency graph with `uv sync --all-extras --locked`.
- Ruff passed with the repository rule set.
- Strict mypy passed across 68 source files.
- The package installs as `prodkit-storage==0.4.0` under Python 3.12 in CI and advertises the supported Python range from package metadata.
- The optional `vector` extra resolves and installs pgvector without making it a mandatory dependency for ordinary consumers.

### PostgreSQL, pgvector, PostGIS, Alembic, and schema safety

- PostgreSQL 18.6/PostGIS 3.6 service health passed.
- A separate PostgreSQL 18.6 + pgvector 0.8.6 service passed live capability validation.
- Privileged PostGIS/pgcrypto/vector bootstrap occurred in CI infrastructure, outside routine Alembic migrations and runtime code.
- `prodkit-storage capabilities` proved PostGIS, GIN, and text-search configuration discovery on the primary CI database.
- The same CLI proved the `vector` extension and HNSW/IVFFlat access methods on the pgvector database.
- Alembic generated the full offline upgrade SQL and upgraded a fresh database to `20260807_0002`.
- `alembic current`, `heads`, and `history` agree on one head.
- Sync and async `prodkit-storage schema-check` both report the expected revision as current.
- `alembic check` reports no metadata drift.
- Published Alembic revisions are checked for immutability; newly added revisions are subjected to the migration-safety linter.
- A one-step downgrade to `20260806_0001`, roll-forward to head, metadata-drift check, and sync/async schema-compatibility verification all passed.
- Live migration-helper tests passed for concurrent indexes and the existing migration-hardening primitives.
- The v0.4.0 PostgreSQL capability integration test created and inspected native GIN and pgvector HNSW indexes, exercised full-text matching, nearest-vector ordering, and a read-only repeatable-read snapshot.

### Data isolation, transactions, and backfills

- A real non-superuser/non-`BYPASSRLS` runtime role was tested against an RLS-protected table: tenants see only their own rows and PostgreSQL rejects a cross-tenant write.
- Read-only transaction enforcement rejects writes at the database level.
- Append-only audit-role behavior permits the required audit insert path while denying unauthorized history reads.
- Stale outbox workers cannot complete events after lease reclamation.
- Joined-eager-load keyset pagination exercises SQLAlchemy `unique()` semantics.
- A live resumable-backfill test proves an interrupted batch and checkpoint roll back together and later resume from the committed checkpoint.

### Redis and coordination

- Live Redis tests passed for atomic cache-tag invalidation, idempotency, token-owned locks, token-bucket rate limiting, and Streams publication.
- The dependency-failure smoke verified unavailable PostgreSQL and Redis report failure promptly instead of hanging or returning a false healthy result.

### Backup, restore, and load smoke

- CI performed a real logical `pg_dump` -> scratch-database `pg_restore` using the PostgreSQL service container's matching client version.
- Source and restored row counts matched for the shared storage/version tables and PostGIS spatial reference data.
- The concurrent DB/Redis saturation smoke completed 40/40 iterations at concurrency 8 with zero errors. In the final hardening run, database p95 was about 40.45 ms and Redis p95 about 17.97 ms, below the deliberately generous CI regression thresholds.

### Tests and coverage

- **107 tests passed** in the complete unit + live integration suite.
- Statement/branch coverage was **81.49%**, above the configured 80% release threshold.
- The suite includes database behavior, infrastructure health, migrations, resumable backfills, Redis behavior, RLS tenant isolation, PostgreSQL capability discovery, native FTS, pgvector HNSW, index introspection, and repeatable-read snapshots.

### Supply-chain and release checks

- `pip-audit` passed against the locked Python dependency graph.
- The runtime Docker image built successfully after applying current Debian security updates in the image layer.
- Trivy HIGH/CRITICAL image scanning passed under the repository's reviewed policy.
- An SPDX JSON SBOM was generated and uploaded successfully.
- Normal CI runs with repository `contents: read` permission.
- The permanent release workflow requires `release/vX.Y.Z` to resolve exactly to current `main`.
- Release publication builds a wheel, sdist, exact-source archive, and `SHA256SUMS`; the publisher verifies GitHub asset size and SHA-256 metadata before making a release non-draft.
- A published tag is treated as immutable and a rerun fails closed if it targets different source or different assets.

## What this validation proves

These checks provide strong evidence that the reusable storage foundation's code, migrations, PostgreSQL capability primitives, concurrency and tenant-isolation behavior, backup/restore smoke, supply-chain controls, and release mechanics behave as intended in the CI environment.

They do **not** prove that every consuming deployment is production-ready. Each product and platform still owns production data classification/retention rules, private networking and TLS, secret rotation, total connection budgets, extension provisioning/upgrades, managed backup/PITR retention, multi-zone failover, measured RPO/RTO, production-scale data/query profiles, ANN recall/latency targets, alert routing/on-call ownership, and compliance requirements.

The shipped load and failure exercises are regression smokes, not capacity benchmarks or chaos-certification results. Provider-specific restore/failover drills and sustained real-application dogfooding remain required evidence before a future `1.0.0` stability claim.
