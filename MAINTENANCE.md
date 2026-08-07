# Maintenance policy (frozen baseline)

**Status:** target baseline **v0.3.0** as an internal application storage foundation.
Prefer bugfixes and proven shared needs only after each tagged release.

This package is intentionally stable. Prefer shipping product features in consuming applications over expanding this library.

## Goals

- Keep a small, typed persistence foundation for PostgreSQL/PostGIS, SQLAlchemy, Alembic, and Redis.
- Avoid becoming a second framework on top of SQLAlchemy.
- Make upgrades in apps deliberate (pinned tags or exact versions only).
- Turn critical persistence safety practices into executable release checks where a reusable library can do so honestly.

## What is frozen

The public import surface in `prodkit_storage/__init__.py` is the primary contract:

- `StorageSettings`
- `SyncDatabase` / `AsyncDatabase`
- `SyncRedis` / `AsyncRedis`
- `SyncUnitOfWork` / `AsyncUnitOfWork`
- `Base`
- `RequestContext`, `request_context`, `tenant_context`
- schema compatibility constants/policies/reports and sync/async checks

Documented helpers under `prodkit_storage.database`, `prodkit_storage.redis`, `prodkit_storage.spatial`, audit/outbox, and the `prodkit-storage` CLI are also part of the consumer surface. Prefer the package root exports when possible.

## Allowed changes

| Change | When |
|--------|------|
| Bug fixes | Broken behavior, incorrect semantics, data-risk bugs |
| Security / dependency CVEs | Known vulnerabilities in this package or its deps |
| Consumer docs | Clearer install, pin, and boundary guidance |
| Operational guardrails | Reusable checks that prevent migration/data/isolation incidents |
| Tiny shared APIs | Only when **two or more** apps need the same helper |

## Not allowed without a proven need

- New Redis/DB primitives “for completeness”
- Domain models for a specific product
- Breaking renames or API redesigns without a major version
- Replacing SQLAlchemy/Redis with alternate stacks
- Becoming a managed hosting, backup, failover, or multi-region orchestration product
- Provider-specific infrastructure code presented as universally production-ready

## Versioning

| Version bump | Meaning |
|--------------|---------|
| Patch `0.x.y` | Compatible correctness, security, and operational hardening fixes |
| Minor `0.x.0` | Additive APIs; pre-1.0 breaking changes require explicit migration notes |
| Major `1.0.0+` | Stable compatibility contract; breaking changes require a major bump |

Release process:

1. Create a focused branch from the current default branch.
2. Change code, tests, documentation, and version metadata on that branch.
3. Open a pull request and require the repository CI/security checks to pass.
4. Review the migration and compatibility impact before merging.
5. Merge the pull request into `main` without rewriting published history.
6. Tag the merged release commit as `vX.Y.Z`.
7. Bump the pin in each consuming app deliberately.

Never depend on floating `main` from production apps. Always pin a tag (or exact commit).
Never move or rewrite a published release tag.
Published Alembic revision files are immutable; add a new revision instead of editing a released one.

## Ownership boundary

| This package owns | Each app/platform owns |
|-------------------|-------------------------|
| Engines, pools, sessions, UoW, repository helpers | Domain models and product schema |
| Audit/outbox primitives | Business workflows and consumers |
| Mixins, pagination, locks, RLS helpers | Product-specific policies and key naming |
| Foundation migrations for shared tables it ships | App Alembic revisions for app tables |
| Migration/schema safety checks | App migration intent and production rollout decisions |
| Backup/restore and load-smoke verification examples | Backup retention, PITR, RPO/RTO, HA/failover |
| Config prefix `PRODKIT_STORAGE_*` | Deployment secrets, managed Postgres/Redis |

## Default decision

If a change is not required by a production path or by two independent consumers, **do not change this repo**. Implement it in the application instead.
