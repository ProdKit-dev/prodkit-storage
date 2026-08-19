# ProdKit Storage

A standalone, typed Python foundation for enterprise SaaS persistence using PostgreSQL, PostGIS, SQLAlchemy, Alembic, and Redis. It exposes parallel synchronous and asynchronous APIs, keeps transaction boundaries explicit, and provides reusable low-level PostgreSQL capability primitives without absorbing application or search-domain semantics.

> ProdKit Storage is an application storage foundation, not a managed database service. Backups, replication, failover, capacity management, privileged extension lifecycle, encryption keys, network policy, and incident response remain deployment responsibilities.

## Included

### PostgreSQL and SQLAlchemy

- Sync SQLAlchemy with psycopg 3 and async SQLAlchemy with asyncpg
- Dedicated write and explicit read-replica engines
- Bounded pools, pre-ping, recycling, connect/statement/lock/idle-transaction timeouts
- Typed declarative base and reusable UUID, timestamp, tenant, soft-delete, external-ID, and optimistic-lock mixins
- Explicit session, transaction, read-session, read-only transaction, and unit-of-work APIs
- Typed read/write session intent for sync and async callers
- Generic sync/async repositories with loader options, streaming, row locking, and bulk operations
- Allowlisted filtering and deterministic multi-column sorting with explicit null placement
- Sort- and query-bound signed keyset pagination plus optional offset pagination
- Serialization/deadlock transaction retry helpers
- Transaction-scoped PostgreSQL advisory locks
- Optional tenant, actor, and request context propagated with `SET LOCAL` semantics
- PostgreSQL SQLSTATE classification and strict string/integer/native enum helpers
- Process-aware client identity, slow-query logging, telemetry, and component health probes
- Read-only sync/async PostgreSQL capability discovery for server versions, extensions, access methods, and text-search configurations
- Fail-closed capability requirements exposed through Python and the `prodkit-storage capabilities` CLI
- PostgreSQL-native `tsvector`/`tsquery` expression helpers and GIN migration primitives
- Optional pgvector SQLAlchemy types plus HNSW/IVFFlat operator-class and migration helpers
- Advanced concurrent-index DDL with access methods, operator classes, storage parameters, predicates, and included columns
- Sync/async index introspection with validity/readiness checks
- Generic JSONB expression helpers and explicit repeatable-read snapshot contexts

### Multi-tenancy and auditability

- Application tenant context through `contextvars`
- Optional PostgreSQL Row-Level Security integration
- Safe Alembic helpers for RLS policies
- Audit event model with classification/redaction and append-only runtime-role grants
- Runtime-role and protected-table RLS verification
- Transactional outbox with `FOR UPDATE SKIP LOCKED`, per-claim lease tokens, optimistic versions, retries, stale-lease recovery, and dead-letter state

### PostGIS

- Geometry/geography type factories
- WGS84 point creation and validation
- Distance, radius, intersection, containment, and bounding-box expressions
- Spatial indexes through GeoAlchemy2

### Redis

- Sync and async pooled clients
- Retry, health-check, timeout, and lifecycle handling
- JSON cache with TTL jitter, atomic tag invalidation, and stampede protection
- Token-safe distributed locks with Lua release/extension
- Idempotency lease and replay state machine
- Atomic server-time token-bucket rate limiter
- Redis Streams publisher
- Health probes and command-level OpenTelemetry metrics

### Operations and release safety

- Bundled Alembic environment and versioned shared-table migrations
- Explicit owner/migrator role separation with `SET ROLE` support
- CLI for migrations, schema compatibility, dependency health, migration safety, and PostgreSQL capabilities
- PostgreSQL 18/PostGIS 3.6, PostgreSQL 18/pgvector, and Redis 8 CI coverage
- Active GitHub Actions CI with lockfile verification, linting, strict typing, full tests, live integrations, migration drift/rollback checks, backup/restore, load/failure smokes, dependency auditing, image scanning, and SPDX SBOM generation
- Permanent exact-`main` release gate that builds wheel, sdist, exact-source archive, and `SHA256SUMS`, then verifies remote GitHub asset digests before publication
- Optional FastAPI, Pydantic, OpenTelemetry, vector, spatial-shape, and secret-provider integrations
- Production guidance for RLS, replicas, pooling, migrations, extension readiness, backup/PITR, Redis durability, and disaster recovery

## Quick start

```bash
cp .env.example .env
uv sync --all-extras
docker compose up -d --wait
uv run prodkit-storage upgrade head
uv run prodkit-storage doctor
uv run prodkit-storage capabilities \
  --require-extension postgis \
  --require-access-method gin \
  --require-text-search-config simple
uv run pytest
```

The development services bind only to loopback:

- PostgreSQL/PostGIS: `127.0.0.1:5432`
- Redis: `127.0.0.1:6379`

The dedicated pgvector database is a CI validation service rather than an additional runtime dependency for ordinary consumers.

## Installation from another repository

Pin immutable releases rather than floating `main`:

```bash
uv add "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0"
```

Install pgvector integration only when a consumer needs it:

```bash
uv add "prodkit-storage[vector] @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0"
```

See [`docs/consuming.md`](docs/consuming.md) for the complete consumer contract.

## Configuration

All settings use the `PRODKIT_STORAGE_` prefix.

```dotenv
PRODKIT_STORAGE_ENVIRONMENT=production
PRODKIT_STORAGE_DATABASE_URL=postgresql://user:password@db:5432/app
PRODKIT_STORAGE_REDIS_URL=rediss://user:password@redis:6379/0
PRODKIT_STORAGE_CURSOR_SIGNING_SECRET=<at-least-32-random-bytes>
```

`staging` and `production` reject the package's known development cursor secret. A plain PostgreSQL URL is converted to:

- `postgresql+psycopg://` for sync access
- `postgresql+asyncpg://` for async access

Explicit driver URLs and read-replica URLs can be supplied separately. Secrets are represented with Pydantic `SecretStr` and are not printed in normal model representations.

For application-model autogeneration, list modules that import models inheriting `prodkit_storage.Base`:

```dotenv
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models,myapp.billing.models
```

For the recommended `NOINHERIT` migrator/owner role split, also set:

```dotenv
PRODKIT_STORAGE_MIGRATION_OWNER_ROLE=prodkit_owner
```

## Synchronous usage

```python
from sqlalchemy import select

from prodkit_storage import StorageSettings, SyncDatabase
from prodkit_storage.database.repository import SyncRepository
from myapp.models import Customer

settings = StorageSettings()
database = SyncDatabase(settings)

try:
    with database.transaction() as session:
        customers = SyncRepository(session, Customer)
        customer = customers.require(customer_id, for_update=True)
        customer.name = "Updated name"
finally:
    database.dispose()
```

Read replicas are explicit:

```python
with database.read_transaction() as session:
    rows = session.scalars(select(Customer)).all()
```

Do not use a replica for a flow that needs immediate read-your-writes consistency unless the infrastructure provides the required replication guarantee.

Repositories exclude soft-deleted rows by default. Pass `include_deleted=True` only for explicit administrative or restoration workflows.

## Asynchronous usage

```python
from prodkit_storage import AsyncDatabase, StorageSettings
from prodkit_storage.database.repository import AsyncRepository
from myapp.models import Customer

async def update_customer(customer_id):
    database = AsyncDatabase(StorageSettings())
    try:
        async with database.transaction() as session:
            customers = AsyncRepository(session, Customer)
            customer = await customers.require(customer_id, for_update=True)
            customer.name = "Updated name"
    finally:
        await database.dispose()
```

## Query foundation

Sorting, filtering, and pagination are explicit and allowlisted. Public API names are mapped to SQLAlchemy expressions by each domain instead of accepting raw column names.

```python
from sqlalchemy import select

from prodkit_storage.database.pagination import CursorCodec
from prodkit_storage.database.sorting import SortRegistry

sorting = SortRegistry(
    name="customer-list-v1",
    fields={
        "created_at": Customer.created_at,
        "name": Customer.name,
        "id": Customer.id,
    },
    default=("-created_at",),
    tie_breaker="id",
)
sort = sorting.parse(requested_sorting)

page = await customers.paginate_cursor(
    select(Customer),
    sort=sort,
    codec=CursorCodec(settings.cursor_secret_bytes),
    cursor=cursor,
    limit=50,
    query_fingerprint="active-customers-v1",
)
```

The cursor authenticates the sort definition, last-row values, and optional query fingerprint. Both sync and async cursor paths de-duplicate ORM scalar results so joined eager loads follow SQLAlchemy's `unique()` requirement.

Use offset pagination when exact totals or direct page navigation are more important than deep-page performance. Repositories also support loader options, `FOR UPDATE NOWAIT`, `FOR UPDATE SKIP LOCKED`, streaming with `yield_per`, count-safe subqueries, and explicit flush/refresh behavior. See [`docs/querying.md`](docs/querying.md).

## PostgreSQL capability layer

The v0.4.0 capability layer is deliberately mechanical. Storage exposes PostgreSQL primitives; consumers choose product semantics.

```python
from prodkit_storage.database import (
    VectorDistance,
    inspect_postgresql_capabilities_sync,
    repeatable_read_sync,
    vector_operator_class,
)

with database.write_engine.connect() as connection:
    capabilities = inspect_postgresql_capabilities_sync(connection)

if not capabilities.has_extension("vector"):
    raise RuntimeError("deployment must provision pgvector")

operator_class = vector_operator_class(
    "vector",
    VectorDistance.COSINE,
    method="hnsw",
)
```

Storage owns capability discovery, SQLAlchemy types/expressions, safe index DDL/introspection, JSONB mechanics, and stable snapshots. A specialized package such as ProdKit Search owns document projections, analyzers, embeddings, query interpretation, ranking, hybrid fusion, highlighting, suggestions, pagination semantics, and search-index lifecycle.

PostgreSQL extensions are deployment-owned. Runtime code and routine Alembic migrations never silently install or upgrade `vector`, PostGIS, pgcrypto, or other privileged extensions. See [`docs/postgresql-capabilities.md`](docs/postgresql-capabilities.md).

## Request and tenant context

```python
from uuid import UUID

from prodkit_storage import RequestContext, request_context

with request_context(
    RequestContext(
        tenant_id=UUID("19dd5df5-cf1f-461f-80fb-50b47be112f0"),
        actor_id=UUID("dd10f1a1-297b-4512-9ca2-540322f99bd0"),
        request_id="req_01JXYZ",
        trace_id="trace_01JXYZ",
    )
):
    with database.transaction() as session:
        ...
```

Enable RLS only after creating policies and using a runtime database role that does not own the protected tables:

```dotenv
PRODKIT_STORAGE_TENANT_RLS_ENABLED=true
PRODKIT_STORAGE_TENANT_REQUIRED=true
```

See [`docs/tenancy.md`](docs/tenancy.md).

## Security and observability integrations

Install optional integrations as needed:

```bash
uv add "prodkit-storage[fastapi,observability]"
```

The security layer provides audit field classification/redaction, sync and async secret-provider protocols, PostgreSQL role bootstrap/post-migration grant templates, and RLS deployment verification. The Pydantic integration rejects PostgreSQL-incompatible NUL characters and provides bounded integer/string helpers.

When observability is enabled, the runtime emits database query, transaction, pool, Redis, and outbox metrics and preserves request, trace, actor, tenant, process, component, and instance correlation. Exporters, sampling, SLOs, and alerts remain application/deployment responsibilities.

See [`docs/security.md`](docs/security.md) and [`docs/observability.md`](docs/observability.md).

## Transactional outbox

Enqueue the event in the same transaction as domain changes:

```python
from prodkit_storage.outbox import enqueue_outbox_event

with database.transaction() as session:
    order.status = "paid"
    enqueue_outbox_event(
        session,
        topic="orders",
        event_type="order.paid",
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={"order_id": str(order.id)},
    )
```

Workers claim with row locking and skip locked rows. Each claim receives a fresh lease token. A stale worker cannot complete an event after a newer worker reclaims it; ownership-checked completion fails rather than overwriting the newer claim. Publication remains at least once, so downstream consumers must be idempotent.

## Redis cache

```python
from prodkit_storage import StorageSettings, SyncRedis
from prodkit_storage.redis import KeyBuilder, SyncCache

settings = StorageSettings()
redis_runtime = SyncRedis(settings)
keys = KeyBuilder(settings.cache_namespace)
cache = SyncCache(
    redis_runtime.client,
    keys,
    default_ttl_seconds=settings.cache_default_ttl_seconds,
    jitter_ratio=settings.cache_ttl_jitter_ratio,
)

key = keys.build("tenant", tenant_id, "customer", customer_id)
customer = cache.get_or_set(
    key,
    lambda: load_customer(customer_id),
    tags=[f"tenant:{tenant_id}", f"customer:{customer_id}"],
)
```

Tag invalidation is one Redis Lua operation. Use separate Redis deployments or namespaces for cache, durable idempotency, locks, streams, and rate limiting when their durability or eviction requirements differ.

## PostGIS query

```python
from sqlalchemy import select

from prodkit_storage.spatial import distance_meters, within_distance
from myapp.models import Place

statement = (
    select(
        Place,
        distance_meters(Place.location, 29.0, 41.0).label("distance_m"),
    )
    .where(within_distance(Place.location, 29.0, 41.0, 5_000))
    .order_by("distance_m")
)
```

Longitude is always supplied before latitude.

## Alembic

```bash
uv run prodkit-storage upgrade head
uv run prodkit-storage downgrade -1
uv run alembic revision --autogenerate -m "add customer table"
```

Routine migrations create or alter application objects only. PostGIS, pgcrypto, `pg_stat_statements`, `vector`, and other privileged extensions belong to database bootstrap/infrastructure. Concurrent GIN/HNSW/IVFFlat builds should be treated as deliberate migration operations with production-shaped resource and query-plan validation.

When owner/migrator separation is used, Alembic connects as the migrator and `SET ROLE`s to `PRODKIT_STORAGE_MIGRATION_OWNER_ROLE` before applying schema changes. See [`docs/migrations.md`](docs/migrations.md).

## Production boundaries

This repository deliberately does not hide important architecture decisions:

- It does not automatically route arbitrary ORM reads to replicas.
- It does not claim exactly-once delivery; it provides an at-least-once transactional outbox foundation.
- It does not auto-enable RLS on application tables.
- It does not silently install or upgrade privileged PostgreSQL extensions.
- It does not make Redis a source of truth for business records.
- It does not choose embeddings, analyzers, ranking, hybrid fusion, or search-index lifecycle.
- It does not implement database backups, failover, sharding, or schema-per-tenant provisioning.
- It does not replace authorization, encryption/key management, data classification, or retention policy.

Read the architecture and operational contracts before deployment:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/postgresql-capabilities.md`](docs/postgresql-capabilities.md)
- [`docs/consuming.md`](docs/consuming.md)
- [`docs/tenancy.md`](docs/tenancy.md)
- [`docs/querying.md`](docs/querying.md)
- [`docs/security.md`](docs/security.md)
- [`docs/observability.md`](docs/observability.md)
- [`docs/migrations.md`](docs/migrations.md)
- [`docs/operations.md`](docs/operations.md)
- [`docs/enterprise-checklist.md`](docs/enterprise-checklist.md)
- [`VALIDATION.md`](VALIDATION.md)
- [`ROADMAP.md`](ROADMAP.md)
- [`MAINTENANCE.md`](MAINTENANCE.md)
