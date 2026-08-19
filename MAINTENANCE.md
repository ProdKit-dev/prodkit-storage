# Maintenance policy (frozen baseline)

**Status:** target baseline **v0.4.0** as an internal application storage foundation. Prefer bugfixes and proven shared needs only after each tagged release.

This package is intentionally stable. Prefer shipping product features in consuming applications over expanding this library.

## Goals

- Keep a small, typed persistence foundation for PostgreSQL/PostGIS, SQLAlchemy, Alembic, and Redis.
- Provide reusable PostgreSQL capability primitives when multiple ProdKit consumers need the same low-level behavior.
- Avoid becoming a second framework on top of SQLAlchemy or a domain-specific search/analytics layer.
- Make upgrades in apps deliberate through immutable tags or exact versions.
- Turn critical persistence and release-safety practices into executable checks where a reusable library can do so honestly.

## What is frozen

The public import surface in `prodkit_storage/__init__.py` is the primary contract:

- `StorageSettings`
- `SyncDatabase` / `AsyncDatabase`
- `SyncRedis` / `AsyncRedis`
- `SyncUnitOfWork` / `AsyncUnitOfWork`
- `Base`
- `RequestContext`, `request_context`, `tenant_context`
- schema compatibility constants/policies/reports and sync/async checks

Documented helpers under `prodkit_storage.database`, `prodkit_storage.redis`, `prodkit_storage.spatial`, audit/outbox, and the `prodkit-storage` CLI are also part of the consumer surface. Prefer the package-root exports when possible. PostgreSQL capability/vector/FTS/index helpers intentionally live under `prodkit_storage.database` so the stable package-root API does not grow for specialized consumers.

## Allowed changes

| Change | When |
|--------|------|
| Bug fixes | Broken behavior, incorrect semantics, data-risk bugs |
| Security / dependency CVEs | Known vulnerabilities in this package or its dependencies |
| Consumer docs | Clearer install, pin, boundary, migration, readiness, and operational guidance |
| Operational guardrails | Reusable checks that prevent migration/data/isolation/release incidents |
| Tiny shared APIs | Only when **two or more** independent consumers need the same helper |
| PostgreSQL capability primitives | Proven shared low-level needs such as extension discovery, reusable index DDL/introspection, FTS/vector types, or stable inspection snapshots |

## Not allowed without a proven need

- New Redis/DB primitives “for completeness”
- Domain models for a specific product
- Search-domain semantics such as embeddings, ranking, hybrid fusion, suggestions, highlighting, query interpretation, or search-index lifecycle
- Breaking renames or API redesigns without the appropriate version/migration contract
- Replacing SQLAlchemy/Redis with alternate stacks
- Becoming a managed hosting, backup, failover, sharding, or multi-region orchestration product
- Provider-specific infrastructure code presented as universally production-ready
- Runtime or routine migration code that silently installs/upgrades privileged PostgreSQL extensions
- Runtime schema/index auto-repair that mutates production because an inspection check failed

## Versioning

| Version bump | Meaning |
|--------------|---------|
| Patch `0.x.y` | Compatible correctness, security, documentation, and operational hardening fixes |
| Minor `0.x.0` | Additive APIs; pre-1.0 breaking changes require explicit migration notes |
| Major `1.0.0+` | Stable compatibility contract; breaking changes require a major bump |

`pyproject.toml` is the release-version source of truth. Do not introduce a second version file unless the repository deliberately adopts one and validates synchronization.

## Release process

1. Create a focused branch from the current protected `main`.
2. Change code, tests, documentation, changelog, validation evidence, and version metadata together when the release requires them.
3. Open a pull request and require the permanent repository `test` and `security` checks to pass on the exact PR head.
4. Review migration, compatibility, security, ownership-boundary, and operational impact before merging.
5. Squash-merge with an expected-head guard so GitHub rejects the merge if the validated source moves.
6. Verify the merged source is the intended tree and that current `main` contains the complete release documentation.
7. Create or fast-forward `release/vX.Y.Z` to **exact current `main`**. Never promote a stale release branch.
8. The permanent Release workflow must verify the branch name matches `pyproject.toml`, verify exact `main`, rerun locked static/test gates, build wheel/sdist/source archive, generate `SHA256SUMS`, and publish through the fail-closed digest-verifying publisher.
9. Verify the immutable `vX.Y.Z` tag resolves exactly to the release commit and the GitHub Release is non-draft/non-prerelease with the complete verified asset set.
10. Delete merged development branches and the temporary release branch only after release verification. The release workflow self-deletes the release branch after successful publication.

Never depend on floating `main` from production apps. Always pin a tag or exact commit.
Never move or rewrite a published release tag.
Published Alembic revision files are immutable; add a new revision instead of editing a released one.
Never weaken CI, migration safety, vulnerability scanning, checksum validation, or source verification merely to make a release pass.

## Release documentation contract

Before an immutable tag is published, these documents must agree with the source being released:

- `README.md` — current capabilities, installation and boundaries;
- `docs/architecture.md` — ownership and dependency direction;
- `docs/operations.md` — production acceptance and operator responsibilities;
- `docs/enterprise-checklist.md` — deployment acceptance checklist;
- `docs/consuming.md` — current pin/install/upgrade guidance;
- `VALIDATION.md` — exact evidence from the current release candidate;
- `CHANGELOG.md` — release-visible changes;
- `ROADMAP.md` — what is complete, stabilization scope, and explicit non-goals;
- this maintenance policy — versioning, ownership and release rules.

If documentation materially disagrees with code before publication, fix and revalidate `main` first. Do not publish and plan to repair the same immutable release afterward.

## Ownership boundary

| This package owns | Each app/platform owns |
|-------------------|-------------------------|
| Engines, pools, sessions, UoW, repository helpers | Domain models and product schema |
| Audit/outbox primitives | Business workflows and consumers |
| Mixins, pagination, locks, RLS helpers | Product-specific policies and key naming |
| PostgreSQL capability/type/index/snapshot primitives | Search ranking, embeddings, query semantics, projection/index lifecycle |
| Foundation migrations for shared tables it ships | App Alembic revisions for app tables |
| Migration/schema safety checks | App migration intent and production rollout decisions |
| Backup/restore and load-smoke verification examples | Backup retention, PITR, RPO/RTO, HA/failover |
| Exact-source release verification and artifact checksums | Consumer deployment/signing/publishing policy beyond this repository |
| Config prefix `PRODKIT_STORAGE_*` | Deployment secrets, managed Postgres/Redis, extension provisioning/upgrades |

## Roadmap rule

[`ROADMAP.md`](ROADMAP.md) records the current baseline and candidate future categories. It is not permission to implement speculative features. A future minor release is justified only when production evidence shows the same low-level persistence capability is required by multiple independent consumers and Storage is the correct ownership boundary.

## Default decision

If a change is not required by a production path or by two independent consumers, **do not change this repo**. Implement it in the application or specialized package instead.
