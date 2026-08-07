#!/usr/bin/env python3
"""Verify unavailable PostgreSQL/Redis dependencies fail visibly and promptly."""

from __future__ import annotations

import json
import socket

from pydantic import SecretStr

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.health import check_sync_database
from prodkit_storage.database.runtime import SyncDatabase
from prodkit_storage.redis.health import check_sync_redis
from prodkit_storage.redis.runtime import SyncRedis


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run() -> dict[str, object]:
    postgres_port = _unused_local_port()
    redis_port = _unused_local_port()
    settings = StorageSettings(
        environment="test",
        database_url=SecretStr(
            f"postgresql://prodkit:prodkit@127.0.0.1:{postgres_port}/prodkit"
        ),
        redis_url=SecretStr(f"redis://127.0.0.1:{redis_port}/0"),
        connect_timeout_seconds=1,
        pool_timeout_seconds=1,
        redis_connect_timeout_seconds=0.2,
        redis_socket_timeout_seconds=0.2,
        redis_retry_attempts=0,
    )
    database = SyncDatabase(settings)
    redis = SyncRedis(settings)
    try:
        database_health = check_sync_database(database.write_engine)
        redis_health = check_sync_redis(redis.client)
    finally:
        redis.close()
        database.dispose()

    healthy = (
        not database_health.healthy
        and database_health.error is not None
        and database_health.latency_ms < 5_000
        and not redis_health.healthy
        and redis_health.error is not None
        and redis_health.latency_ms < 5_000
    )
    return {
        "healthy": healthy,
        "database": {
            "failed_as_expected": not database_health.healthy,
            "latency_ms": database_health.latency_ms,
            "error_type": (
                database_health.error.split(":", 1)[0]
                if database_health.error is not None
                else None
            ),
        },
        "redis": {
            "failed_as_expected": not redis_health.healthy,
            "latency_ms": redis_health.latency_ms,
            "error_type": (
                redis_health.error.split(":", 1)[0]
                if redis_health.error is not None
                else None
            ),
        },
    }


def main() -> int:
    report = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if bool(report["healthy"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
