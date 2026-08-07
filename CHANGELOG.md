# Changelog

All notable changes are documented here. The project follows semantic
versioning after `1.0.0`; pre-1.0 minor releases may introduce documented
breaking changes.

## 0.2.1 - 2026-08-07

### Fixed

- Activated the GitHub Actions workflow under `.github/workflows/` so lint,
  typing, migrations, tests, dependency audit, image scanning, and SBOM jobs
  actually execute.
- Added explicit Alembic `SET ROLE` support for a `NOINHERIT` migrator/owner
  split so schema objects are owned by the dedicated owner role and owner-scoped
  default privileges apply consistently.
- Removed privileged extension installation from routine Alembic migrations;
  PostGIS and other approved extensions are provisioned by infrastructure/bootstrap.
- Split role bootstrap from post-migration grants and made the shared audit table
  append-only for the runtime role; runtime outbox deletion is also withheld.
- Added per-claim outbox lease tokens plus optimistic versioning and ownership-
  checked completion/failure APIs so stale workers cannot complete reclaimed events.
- De-duplicated synchronous keyset ORM scalar results with SQLAlchemy `unique()`
  semantics, matching the async and offset paths.
- Portable enum types now reject unknown raw values before they reach PostgreSQL.
- Staging and production configurations reject the known development cursor-
  signing secret.
- Redis cache tag invalidation now executes atomically in one Lua script instead
  of a racy `SMEMBERS` followed by client-side deletion.

### Added

- Live PostgreSQL tests for read-only transaction enforcement, joined-eager-load
  cursor pagination, and stale outbox lease rejection.
- Live Redis tests for atomic tag invalidation, idempotency, distributed locks,
  rate limiting, and Streams publication.
- Unit regression coverage for production secret validation, migration role
  identifiers, strict enum binding, audit/outbox grants, and outbox lease loss.
- Migration rollback/roll-forward and Alembic metadata-drift checks in CI.

### Changed

- Maintenance/release guidance now consistently requires branch + pull request +
  passing CI before merging and explicitly forbids moving published tags.
- Production migration and security documentation now separates privileged
  database bootstrap, migrator login identity, object ownership, and runtime grants.

## 0.2.0 - 2026-08-07

### Added

- Allowlisted filtering and deterministic multi-column sorting with explicit
  null placement and unique tie-breakers.
- Sort- and query-bound signed cursor pagination while preserving the legacy
  two-column cursor API.
- Optional offset pagination with safe counts and no-count lookahead.
- Typed sync/async read and write session intent.
- Repository protocols, loader options, streaming, row-lock modes, explicit
  flush/refresh behavior, and bulk operations.
- PostgreSQL SQLSTATE classification and reusable enum column types.
- Process-aware PostgreSQL and Redis client identity.
- Hybrid soft-delete expressions and safe model representations.
- Optional FastAPI dependencies, query parsers, response schemas, and request
  context middleware.
- PostgreSQL-safe Pydantic validators and schema base classes.
- Audit classification, redaction, hashing, rejection, and custom classifier
  hooks.
- Provider-neutral sync/async secret manager contracts and database role SQL
  templates.
- RLS deployment verification for runtime roles and protected tables.
- OpenTelemetry-compatible database, transaction, pool, Redis, request-context,
  and outbox telemetry.
- Dependency auditing, container scanning, SBOM generation, Dependabot, and a
  security response policy.

### Changed

- Audit event helpers sanitize snapshots and metadata by default.
- Database and Redis clients expose service, process, component, and instance
  identity.
- The package version is now `0.2.0` and optional integration extras are
  declared explicitly.
