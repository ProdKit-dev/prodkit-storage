"""Operational CLI for health checks, schema safety, and Alembic migrations."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from alembic import command
from alembic.config import Config

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.health import check_async_database, check_sync_database
from prodkit_storage.database.migration_safety import inspect_migration_file
from prodkit_storage.database.runtime import AsyncDatabase, SyncDatabase
from prodkit_storage.database.schema_compatibility import (
    check_schema_compatibility_async,
    check_schema_compatibility_sync,
)
from prodkit_storage.redis.health import check_async_redis, check_sync_redis
from prodkit_storage.redis.runtime import AsyncRedis, SyncRedis


def _alembic_config(settings: StorageSettings, *, async_driver: bool = False) -> Config:
    package_root = Path(__file__).resolve().parent
    config = Config()
    config.set_main_option("script_location", str(package_root / "alembic"))
    url = settings.async_url if async_driver else settings.sync_url
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


def _doctor_sync(settings: StorageSettings) -> int:
    database = SyncDatabase(settings)
    redis = SyncRedis(settings)
    try:
        result = {
            "database": asdict(check_sync_database(database.write_engine)),
            "redis": asdict(check_sync_redis(redis.client)),
        }
    finally:
        redis.close()
        database.dispose()
    print(json.dumps(result, indent=2, default=str))
    return 0 if all(component["healthy"] for component in result.values()) else 1


async def _doctor_async(settings: StorageSettings) -> int:
    database = AsyncDatabase(settings)
    redis = AsyncRedis(settings)
    try:
        result = {
            "database": asdict(await check_async_database(database.write_engine)),
            "redis": asdict(await check_async_redis(redis.client)),
        }
    finally:
        await redis.close()
        await database.dispose()
    print(json.dumps(result, indent=2, default=str))
    return 0 if all(component["healthy"] for component in result.values()) else 1


def _schema_check_sync(settings: StorageSettings) -> int:
    database = SyncDatabase(settings)
    try:
        with database.session() as session:
            report = check_schema_compatibility_sync(
                session,
                schema=settings.database_schema,
            )
    finally:
        database.dispose()
    print(json.dumps(asdict(report), indent=2, default=str))
    return 0 if report.compatible else 1


async def _schema_check_async(settings: StorageSettings) -> int:
    database = AsyncDatabase(settings)
    try:
        async with database.session() as session:
            report = await check_schema_compatibility_async(
                session,
                schema=settings.database_schema,
            )
    finally:
        await database.dispose()
    print(json.dumps(asdict(report), indent=2, default=str))
    return 0 if report.compatible else 1


def _migration_check(paths: list[str]) -> int:
    blocking = False
    for raw_path in paths:
        report = inspect_migration_file(raw_path)
        for issue in report.issues:
            waived = issue.code in report.waivers
            status = "WAIVED" if waived else issue.severity.value.upper()
            print(f"{report.path}:{issue.line}: {status} {issue.code}: {issue.message}")
        if report.blocking_issues:
            blocking = True
    return 1 if blocking else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prodkit-storage")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check PostgreSQL/PostGIS and Redis")
    doctor.add_argument("--async", dest="async_mode", action="store_true")

    schema_check = subparsers.add_parser(
        "schema-check",
        help="verify the live Alembic revision is compatible with this package",
    )
    schema_check.add_argument("--async", dest="async_mode", action="store_true")

    migration_check = subparsers.add_parser(
        "migration-check",
        help="lint new Alembic revision source for production migration hazards",
    )
    migration_check.add_argument("paths", nargs="+")

    upgrade = subparsers.add_parser("upgrade", help="run Alembic upgrade")
    upgrade.add_argument("revision", nargs="?", default="head")
    upgrade.add_argument("--async", dest="async_mode", action="store_true")

    downgrade = subparsers.add_parser("downgrade", help="run Alembic downgrade")
    downgrade.add_argument("revision")
    downgrade.add_argument("--async", dest="async_mode", action="store_true")

    current = subparsers.add_parser("current", help="show current migration revision")
    current.add_argument("--async", dest="async_mode", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "migration-check":
        return _migration_check(args.paths)

    settings = StorageSettings()
    if args.command == "doctor":
        return asyncio.run(_doctor_async(settings)) if args.async_mode else _doctor_sync(settings)
    if args.command == "schema-check":
        return (
            asyncio.run(_schema_check_async(settings))
            if args.async_mode
            else _schema_check_sync(settings)
        )

    config = _alembic_config(settings, async_driver=args.async_mode)
    if args.command == "upgrade":
        command.upgrade(config, args.revision)
    elif args.command == "downgrade":
        command.downgrade(config, args.revision)
    elif args.command == "current":
        command.current(config, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
