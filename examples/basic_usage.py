from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import text

from prodkit_storage import (
    AsyncDatabase,
    RequestContext,
    StorageSettings,
    SyncDatabase,
    request_context,
)


def sync_example() -> None:
    database = SyncDatabase(StorageSettings())
    try:
        with request_context(RequestContext(tenant_id=uuid4(), request_id="example-sync")):
            with database.transaction() as session:
                assert session.scalar(text("SELECT 1")) == 1
    finally:
        database.dispose()


async def async_example() -> None:
    database = AsyncDatabase(StorageSettings())
    try:
        with request_context(RequestContext(tenant_id=uuid4(), request_id="example-async")):
            async with database.transaction() as session:
                assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await database.dispose()


if __name__ == "__main__":
    sync_example()
    asyncio.run(async_example())
