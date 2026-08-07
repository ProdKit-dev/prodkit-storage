#!/usr/bin/env python3
"""Small deterministic saturation smoke for PostgreSQL pool and Redis latency."""

from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import text

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.runtime import SyncDatabase
from prodkit_storage.redis.runtime import SyncRedis


@dataclass(frozen=True, slots=True)
class Sample:
    database_ms: float
    redis_ms: float


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil((percentile / 100.0) * len(ordered)) - 1, 0)
    return ordered[min(index, len(ordered) - 1)]


def run_smoke(*, iterations: int, concurrency: int) -> tuple[list[Sample], list[str]]:
    settings = StorageSettings()
    database = SyncDatabase(settings)
    redis = SyncRedis(settings)
    errors: list[str] = []

    def sample(_: int) -> Sample:
        database_started = time.perf_counter()
        with database.write_engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
        database_ms = (time.perf_counter() - database_started) * 1000

        redis_started = time.perf_counter()
        if not redis.client.ping():
            raise RuntimeError("Redis PING returned false")
        redis_ms = (time.perf_counter() - redis_started) * 1000
        return Sample(database_ms=database_ms, redis_ms=redis_ms)

    samples: list[Sample] = []
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(sample, index) for index in range(iterations)]
            for future in futures:
                try:
                    samples.append(future.result())
                except Exception as error:
                    errors.append(f"{type(error).__name__}: {error}")
    finally:
        redis.close()
        database.dispose()
    return samples, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--database-p95-ms", type=float, default=1000.0)
    parser.add_argument("--redis-p95-ms", type=float, default=500.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations < 1 or args.concurrency < 1:
        raise SystemExit("iterations and concurrency must be positive")
    samples, errors = run_smoke(iterations=args.iterations, concurrency=args.concurrency)
    database = [sample.database_ms for sample in samples]
    redis = [sample.redis_ms for sample in samples]
    report = {
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "completed": len(samples),
        "errors": errors,
        "database_ms": {
            "p50": _percentile(database, 50),
            "p95": _percentile(database, 95),
            "p99": _percentile(database, 99),
        },
        "redis_ms": {
            "p50": _percentile(redis, 50),
            "p95": _percentile(redis, 95),
            "p99": _percentile(redis, 99),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    healthy = (
        not errors
        and len(samples) == args.iterations
        and report["database_ms"]["p95"] <= args.database_p95_ms
        and report["redis_ms"]["p95"] <= args.redis_p95_ms
    )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
