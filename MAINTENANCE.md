# Maintenance policy (frozen baseline)

**Status:** current baseline **v0.2.0** as an internal application storage foundation.
Prefer bugfixes and proven shared needs only after each tagged release.

This package is intentionally stable. Prefer shipping product features in consuming applications over expanding this library.

## Goals

- Keep a small, typed persistence foundation for PostgreSQL/PostGIS, SQLAlchemy, Alembic, and Redis.
- Avoid becoming a second framework on top of SQLAlchemy.
- Make upgrades in apps deliberate (pinned tags or exact versions only).

## What is frozen

The public import surface in `prodkit_storage/__init__.py` is the primary contract:

- `StorageSettings`
- `SyncDatabase` / `AsyncDatabase`
- `SyncRedis` / `AsyncRedis`
- `SyncUnitOfWork` / `AsyncUnitOfWork`
- `Base`
- `RequestContext`, `request_context`, `tenant_context`

Documented helpers under `prodkit_storage.database`, `prodkit_storage.redis`, `prodkit_storage.spatial`, audit/outbox, and the `prodkit-storage` CLI are also part of the consumer surface. Prefer the package root exports when possible.

## Allowed changes

| Change | When |
|--------|------|
| Bug fixes | Broken behavior, incorrect semantics, data-risk bugs |
| Security / dependency CVEs | Known vulnerabilities in this package or its deps |
| Consumer docs | Clearer install, pin, and boundary guidance |
| Tiny shared APIs | Only when **two or more** apps need the same helper |

## Not allowed without a proven need

- New Redis/DB primitives “for completeness”
- Domain models for a specific product
- Breaking renames or API redesigns without a major version
- Replacing SQLAlchemy/Redis with alternate stacks
- Expanding scope into hosting, backups, or multi-region orchestration

## Versioning

| Version bump | Meaning |
|--------------|---------|
| Patch `0.1.x` | Bug fixes only; safe for apps to take |
| Minor `0.2.0` | Additive APIs only; no intentional breaks |
| Major `1.0.0` | Breaking changes (rare; prefer app-side adapters) |

Release process:

1. Change code and tests in this repo.
2. Bump `version` in `pyproject.toml`.
3. Commit on `main`.
4. Tag annotated release: `vX.Y.Z`.
5. Push `main` and the tag.
6. Bump the pin in each consuming app deliberately.

Never depend on floating `main` from production apps. Always pin a tag (or exact commit).

## Ownership boundary

| This package owns | Each app owns |
|-------------------|---------------|
| Engines, pools, sessions, UoW, repositories helpers | Domain models and product schema |
| Audit/outbox primitives | Business workflows and consumers |
| Mixins, pagination, locks, RLS helpers | Product-specific policies and key naming |
| Foundation migrations for shared tables it ships | App Alembic revisions for app tables |
| Config prefix `PRODKIT_STORAGE_*` | Deployment secrets, managed Postgres/Redis |

## Default decision

If a change is not required by a production path or by two independent consumers, **do not change this repo**. Implement it in the application instead.
