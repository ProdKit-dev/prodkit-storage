# Using ProdKit Storage from another repository

## Install (recommended: pin a release tag)

With [uv](https://github.com/astral-sh/uv):

```bash
uv add "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.1.0"
```

Or in `pyproject.toml`:

```toml
dependencies = [
  "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.1.0",
]
```

Optional extras:

```bash
uv add "prodkit-storage[shapes,observability] @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.1.0"
```

Private clone over SSH:

```toml
dependencies = [
  "prodkit-storage @ git+ssh://git@github.com/ProdKit-dev/prodkit-storage.git@v0.1.0",
]
```

Local path / editable (development only):

```bash
uv add --editable "../prodkit-storage"
```

## Configuration

In the application environment (see this repo’s `.env.example`):

```dotenv
PRODKIT_STORAGE_DATABASE_URL=postgresql://user:password@db:5432/app
PRODKIT_STORAGE_REDIS_URL=redis://127.0.0.1:6379/0
PRODKIT_STORAGE_CURSOR_SIGNING_SECRET=<at-least-32-random-bytes>
# Optional: modules that import models inheriting prodkit_storage.Base
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models
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

See `examples/consumer/` for a copy-paste starter `pyproject.toml` and module layout notes.

## Upgrade policy

1. Prefer patch tags (`v0.1.1`) for bugfixes.
2. Bump the pin in each app intentionally; do not float on `main`.
3. Run app tests and migrations after every pin bump.

## What not to put in this package

Domain entities, product-specific repositories, and business workflows stay in the application repository.
