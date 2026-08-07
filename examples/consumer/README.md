# Consumer starter

Copy these snippets into a product repository. Do not treat this folder as an installable package.

## 1. Depend on a frozen tag

```toml
# pyproject.toml (application)
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.2.0",
  # "fastapi", "uvicorn", ... your app stack
]
```

Install:

```bash
uv add "prodkit-storage @ git+https://github.com/ProdKit-dev/prodkit-storage.git@v0.2.0"
```

## 2. Environment

```dotenv
PRODKIT_STORAGE_DATABASE_URL=postgresql://user:password@127.0.0.1:5432/myapp
PRODKIT_STORAGE_REDIS_URL=redis://127.0.0.1:6379/0
PRODKIT_STORAGE_CURSOR_SIGNING_SECRET=replace-with-at-least-32-random-bytes
PRODKIT_STORAGE_ALEMBIC_MODEL_MODULES=myapp.models
```

## 3. Domain models live in the app

```python
# myapp/models.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String

from prodkit_storage.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, TenantMixin


class Customer(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
```

## 4. Runtime bootstrap

```python
# myapp/runtime.py
from prodkit_storage import AsyncDatabase, AsyncRedis, StorageSettings

settings = StorageSettings()
database = AsyncDatabase(settings)
redis = AsyncRedis(settings)
```

## 5. Boundary checklist

- [ ] Pin is a **tag** (`@v0.2.0`), not `main`
- [ ] Product tables/models are in the app, not in `prodkit-storage`
- [ ] App owns product migrations
- [ ] Managed Postgres/Redis are deployment concerns of the app
