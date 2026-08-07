import pytest

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.health import check_async_database, check_sync_database
from prodkit_storage.database.runtime import AsyncDatabase, SyncDatabase
from prodkit_storage.redis.health import check_async_redis, check_sync_redis
from prodkit_storage.redis.runtime import AsyncRedis, SyncRedis

pytestmark = pytest.mark.integration


def test_sync_infrastructure() -> None:
    settings = StorageSettings()
    database = SyncDatabase(settings)
    redis = SyncRedis(settings)
    try:
        assert check_sync_database(database.write_engine).healthy
        assert check_sync_redis(redis.client).healthy
    finally:
        redis.close()
        database.dispose()


@pytest.mark.asyncio
async def test_async_infrastructure() -> None:
    settings = StorageSettings()
    database = AsyncDatabase(settings)
    redis = AsyncRedis(settings)
    try:
        assert (await check_async_database(database.write_engine)).healthy
        assert (await check_async_redis(redis.client)).healthy
    finally:
        await redis.close()
        await database.dispose()
