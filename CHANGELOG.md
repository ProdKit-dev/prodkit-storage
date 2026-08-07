# Changelog

All notable changes are documented here. The project follows semantic
versioning after `1.0.0`; pre-1.0 minor releases may introduce documented
breaking changes.

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
