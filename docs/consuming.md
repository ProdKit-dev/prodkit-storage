# Using ProdKit Storage from another repository

## Install

Pin a released version. Production consumers must not float on `main`.

With `uv`:

```bash
uv add "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0"
```

Or in `pyproject.toml`:

```toml
dependencies = [
  "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0",
]
```

Optional extras are additive. For example, a PostgreSQL search/projection adapter that needs pgvector SQLAlchemy types can install:

```bash
uv add "prodkit-storage[vector] @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0"
```

Other integrations can be combined as needed:

```bash
uv add "prodkit-storage[vector,shapes,observability] @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.4.0"
```

Private clone over SSH:

```toml
dependencies = [
  "prodkit-storage @ git+ssh://git@github.com/ProdKit-dev/prodkit-storage.git@v0.4.0",
]
```

Local editable dependency is appropriate only for coordinated development:

```bash
uv add --editable "../prodkit-storage"
```

## Configuration

In the application environment, using this repository's `.env.example` as the baseline:

```dotenv
PRODKIT_STORAGE_ENVIRONMENT=production
PRODKIT_STORAGE_DATABASE_URL=postgresql://user:password@db:5432/app
PRODKIT_STORAGE_REDIS_URL=redis://127.0.0.1:6379/0
PRODKIT_STORAGE_CURSOR_SIGNING_SECRET=<at-least-32-random-bytes>
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models
PRODKIT_STORAGE_MIGRATION_OWNER_ROLE=prodkit_owner
```

Provision approved PostgreSQL extensions such as PostGIS, pgcrypto, `pg_stat_statements`, and `vector` through infrastructure or a privileged database bootstrap. Runtime code and routine application migrations must not silently create or upgrade privileged extensions.

Use the capability command in deployment/readiness checks when a consumer depends on specific PostgreSQL features:

```bash
uv run prodkit-storage capabilities \
  --require-extension vector \
  --require-access-method hnsw \
  --require-text-search-config simple
```

## Minimal application wiring

```python
from prodkit_storage import (
    AsyncDatabase,
    AsyncRedis,
    RequestContext,
    StorageSettings,
    request_context,
)

settings = StorageSettings()
db = AsyncDatabase(settings)
redis = AsyncRedis(settings)

# Use request_context(...) around request/worker units of work.
# Subclass prodkit_storage.database.base.Base for domain models in the app.
# Keep product migrations in the app; upgrade deliberately when pins change.
```

Specialized PostgreSQL primitives are intentionally imported from `prodkit_storage.database` rather than the frozen package-root surface. This includes capability discovery, native full-text expressions, vector types/operator classes, advanced index DDL/introspection, JSONB expressions, and repeatable-read snapshot helpers.

See `examples/consumer/` for a starter layout and [`postgresql-capabilities.md`](postgresql-capabilities.md) for the PostgreSQL capability boundary.

## Upgrade policy

1. Bump the exact release pin intentionally.
2. Read the changelog and migration notes for every minor pre-1.0 upgrade.
3. Run the consuming application's own tests, migrations, role/grant checks, capability checks, and deployment readiness checks.
4. Revalidate ANN/FTS query plans, index build behavior, backup/restore, and capacity when the application uses those features.

## Ownership boundary

ProdKit Storage owns reusable persistence and low-level PostgreSQL mechanics. Domain entities, product-specific repositories, business workflows, authorization semantics, embeddings, ranking, hybrid retrieval, suggestions, and search-index lifecycle stay in the consuming application or specialized package such as ProdKit Search.
