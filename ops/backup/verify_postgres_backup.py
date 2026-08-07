#!/usr/bin/env python3
"""Create a logical PostgreSQL backup, restore it, and compare user-table counts.

The verifier can use local PostgreSQL client binaries or execute the matching
client tools inside a PostgreSQL/PostGIS Docker container. The latter is useful
in CI because pg_dump must not be older than the server it backs up.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url


def _run(command: Sequence[str]) -> None:
    subprocess.run(command, check=True)


def _url_with_database(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


def _connection_parts(url: str) -> tuple[str, str]:
    parsed = make_url(url)
    if parsed.username is None or parsed.database is None:
        raise ValueError("database URL must contain a username and database name")
    return parsed.username, parsed.database


def _table_counts(url: str, schema: str) -> dict[str, int]:
    query = """
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
    """
    counts: dict[str, int] = {}
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (schema,))
            tables = [str(row[0]) for row in cursor.fetchall()]
            for table in tables:
                identifier = psycopg.sql.Identifier(schema, table)
                cursor.execute(psycopg.sql.SQL("SELECT count(*) FROM {}").format(identifier))
                counts[table] = int(cursor.fetchone()[0])
    return counts


def _docker_command(container: str, *args: str) -> list[str]:
    return ["docker", "exec", container, *args]


def verify(
    database_url: str,
    *,
    schema: str,
    docker_container: str | None,
) -> dict[str, object]:
    username, database = _connection_parts(database_url)
    restore_database = f"prodkit_restore_{secrets.token_hex(6)}"
    restore_url = _url_with_database(database_url, restore_database)
    dump_path = Path(f"/tmp/prodkit-storage-{secrets.token_hex(6)}.dump")
    created = False

    if docker_container:
        container_dump = f"/tmp/{dump_path.name}"
        dump_command = _docker_command(
            docker_container,
            "pg_dump",
            "-U",
            username,
            "-d",
            database,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            container_dump,
        )
        create_command = _docker_command(
            docker_container,
            "createdb",
            "-U",
            username,
            restore_database,
        )
        restore_command = _docker_command(
            docker_container,
            "pg_restore",
            "-U",
            username,
            "-d",
            restore_database,
            "--no-owner",
            "--no-acl",
            container_dump,
        )
        drop_command = _docker_command(
            docker_container,
            "dropdb",
            "-U",
            username,
            "--if-exists",
            restore_database,
        )
        cleanup_dump = _docker_command(docker_container, "rm", "-f", container_dump)
    else:
        dump_command = [
            "pg_dump",
            database_url,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(dump_path),
        ]
        create_command = ["createdb", restore_url]
        restore_command = [
            "pg_restore",
            "--dbname",
            restore_url,
            "--no-owner",
            "--no-acl",
            str(dump_path),
        ]
        drop_command = ["dropdb", "--if-exists", restore_url]
        cleanup_dump = ["rm", "-f", str(dump_path)]

    try:
        _run(dump_command)
        _run(create_command)
        created = True
        _run(restore_command)
        source_counts = _table_counts(database_url, schema)
        restored_counts = _table_counts(restore_url, schema)
        if source_counts != restored_counts:
            raise RuntimeError(
                "restored database table counts differ from source: "
                f"source={source_counts!r}, restored={restored_counts!r}"
            )
        return {
            "healthy": True,
            "schema": schema,
            "tables": source_counts,
            "restore_database": restore_database,
        }
    finally:
        if created:
            _run(drop_command)
        _run(cleanup_dump)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--schema", default="public")
    parser.add_argument("--docker-container")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = verify(
            args.database_url,
            schema=args.schema,
            docker_container=args.docker_container,
        )
    except Exception as error:
        print(json.dumps({"healthy": False, "error": f"{type(error).__name__}: {error}"}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
