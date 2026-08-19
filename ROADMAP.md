# ProdKit Storage roadmap

ProdKit Storage is a deliberately small persistence foundation. The roadmap is capability-driven, not feature-count-driven: new surface area is added only when it is reusable across independent consumers and belongs below domain semantics.

## Current baseline: v0.4.0

`v0.4.0` closes the shared low-level PostgreSQL capability layer required by specialized consumers such as ProdKit Search while preserving Storage's boundary.

Completed for this baseline:

- PostgreSQL/PostGIS, SQLAlchemy, Alembic, Redis, sync/async runtimes, repositories, transactions and unit-of-work;
- explicit read replicas, RLS helpers/verification, tenant/request context, audit and transactional outbox;
- Redis cache, locks, idempotency, rate limiting and Streams primitives;
- migration safety, schema compatibility, backup/restore verification, load/failure smokes and supply-chain gates;
- read-only PostgreSQL capability discovery and fail-closed requirements;
- native PostgreSQL full-text primitives around `tsvector`/`tsquery` and GIN;
- optional pgvector SQLAlchemy types for vector/half-vector/sparse-vector/bit data;
- HNSW/IVFFlat operator-class and migration primitives;
- advanced concurrent-index DDL and sync/async index introspection;
- JSONB expression helpers and explicit repeatable-read inspection snapshots;
- permanent exact-main release publication with wheel/sdist/source archive, checksums and remote digest verification.

## v0.4.x: stabilization only

Patch releases should be limited to compatible correctness, security and operational hardening:

- bug fixes discovered by real consumers;
- dependency/CVE updates;
- PostgreSQL/driver compatibility fixes;
- documentation corrections and operational guardrails;
- test/conformance improvements that do not broaden the domain boundary.

A patch release should not add search ranking, embedding generation, hybrid retrieval, domain models, provider orchestration or managed-database behavior.

## Future minor releases

A future `v0.5.0+` is justified only by a proven shared need in at least two independent consumers. Candidate categories—not commitments—include:

- additional generic PostgreSQL index/introspection primitives that cannot be expressed safely by the existing helpers;
- reusable extension/capability version constraints when multiple consumers require them;
- additional stable snapshot/reconciliation mechanics that remain storage-generic;
- compatibility work required by supported PostgreSQL, SQLAlchemy, psycopg, asyncpg, Redis or Python releases;
- reusable migration/data-safety primitives backed by production evidence.

Every candidate must answer all three questions:

1. Is this persistence/infrastructure behavior rather than domain behavior?
2. Do at least two independent consumers need the same abstraction?
3. Can Storage expose it without choosing application semantics or silently operating privileged infrastructure?

If any answer is no, the capability belongs in the consuming repository.

## Explicit non-goals

The roadmap does not include:

- embeddings or model/provider clients;
- lexical/semantic ranking or hybrid fusion;
- query interpretation, suggestions, highlighting or search-index lifecycle;
- analytics/OLAP semantics;
- domain schemas or business repositories;
- automatic schema repair or runtime `CREATE EXTENSION`;
- database hosting, failover orchestration, PITR services, sharding control planes or multi-region topology management.

Those belong in domain packages, specialized systems such as ProdKit Search, or deployment infrastructure.

## Path to 1.0.0

`1.0.0` should represent a compatibility commitment, not a feature milestone. Before declaring it, the project should have:

- sustained use by multiple production consumers;
- a proven stable package-root and documented database-helper API;
- documented compatibility policy across supported Python/PostgreSQL/Redis/SQLAlchemy versions;
- repeatable upgrade evidence across multiple released versions;
- real production feedback on migrations, RLS, outbox, backup/restore and PostgreSQL capability primitives;
- no known boundary ambiguities between Storage and domain-specific packages;
- release provenance/checksum verification proven across multiple releases;
- measured operational evidence beyond CI smokes, including consumer-owned restore/failover exercises.

Until then, pre-1.0 minor releases may evolve additive specialized helper APIs with explicit migration notes, while published tags and Alembic revisions remain immutable.

## Decision rule

The default roadmap decision is **do not add a feature**. Add it only when production evidence shows that the same low-level persistence capability is being reimplemented across independent consumers and Storage is the correct ownership boundary.
