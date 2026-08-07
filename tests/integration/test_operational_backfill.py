from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.backfill import BackfillBatch, run_batched_backfill_sync
from prodkit_storage.database.runtime import SyncDatabase

pytestmark = pytest.mark.integration

_CREATE_ITEMS = """
CREATE TABLE storage_ci_backfill_items (
  id integer PRIMARY KEY,
  migrated boolean NOT NULL DEFAULT false
)
"""
_CREATE_CHECKPOINT = """
CREATE TABLE storage_ci_backfill_checkpoint (
  job_name text PRIMARY KEY,
  last_id integer NOT NULL
)
"""
_DROP_ITEMS = "DROP TABLE IF EXISTS storage_ci_backfill_items"
_DROP_CHECKPOINT = "DROP TABLE IF EXISTS storage_ci_backfill_checkpoint"


def _load_checkpoint(session: Session) -> int:
    value = session.scalar(
        text(
            "SELECT last_id FROM storage_ci_backfill_checkpoint "
            "WHERE job_name = 'items-v1'"
        )
    )
    return int(value or 0)


def _save_checkpoint(session: Session, checkpoint: int | None) -> None:
    if checkpoint is None:
        raise ValueError("test backfill checkpoint must not be null")
    session.execute(
        text(
            "UPDATE storage_ci_backfill_checkpoint "
            "SET last_id = :last_id WHERE job_name = 'items-v1'"
        ),
        {"last_id": checkpoint},
    )


def _process_batch(
    session: Session,
    checkpoint: int | None,
    batch_size: int,
) -> BackfillBatch[int]:
    cursor = int(checkpoint or 0)
    ids = [
        int(value)
        for value in session.scalars(
            text(
                "SELECT id FROM storage_ci_backfill_items "
                "WHERE id > :cursor ORDER BY id LIMIT :limit"
            ),
            {"cursor": cursor, "limit": batch_size},
        ).all()
    ]
    if not ids:
        return BackfillBatch(next_cursor=cursor, processed=0, done=True)
    session.execute(
        text("UPDATE storage_ci_backfill_items SET migrated = true WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    return BackfillBatch(
        next_cursor=ids[-1],
        processed=len(ids),
        done=len(ids) < batch_size,
    )


def test_interrupted_backfill_rolls_back_batch_and_resumes_from_checkpoint() -> None:
    database = SyncDatabase(StorageSettings(environment="test"))
    calls = 0

    def fail_second_batch(
        session: Session,
        checkpoint: int | None,
        batch_size: int,
    ) -> BackfillBatch[int]:
        nonlocal calls
        calls += 1
        batch = _process_batch(session, checkpoint, batch_size)
        if calls == 2:
            raise RuntimeError("simulated worker interruption")
        return batch

    try:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_ITEMS)
            connection.exec_driver_sql(_DROP_CHECKPOINT)
            connection.exec_driver_sql(_CREATE_ITEMS)
            connection.exec_driver_sql(_CREATE_CHECKPOINT)
            connection.execute(
                text(
                    "INSERT INTO storage_ci_backfill_items (id) "
                    "SELECT generate_series(1, 5)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO storage_ci_backfill_checkpoint (job_name, last_id) "
                    "VALUES ('items-v1', 0)"
                )
            )

        with pytest.raises(RuntimeError, match="simulated worker interruption"):
            run_batched_backfill_sync(
                database.write_session_factory,
                load_checkpoint=_load_checkpoint,
                process_batch=fail_second_batch,
                save_checkpoint=_save_checkpoint,
                batch_size=2,
            )

        with database.session() as session:
            assert _load_checkpoint(session) == 2
            migrated = session.execute(
                text("SELECT id, migrated FROM storage_ci_backfill_items ORDER BY id")
            ).all()
            assert migrated == [(1, True), (2, True), (3, False), (4, False), (5, False)]

        result = run_batched_backfill_sync(
            database.write_session_factory,
            load_checkpoint=_load_checkpoint,
            process_batch=_process_batch,
            save_checkpoint=_save_checkpoint,
            batch_size=2,
        )
        assert result.completed
        assert result.processed == 3
        assert result.checkpoint == 5

        with database.session() as session:
            assert _load_checkpoint(session) == 5
            assert session.scalar(
                text("SELECT count(*) FROM storage_ci_backfill_items WHERE migrated")
            ) == 5
    finally:
        with database.write_engine.begin() as connection:
            connection.exec_driver_sql(_DROP_ITEMS)
            connection.exec_driver_sql(_DROP_CHECKPOINT)
        database.dispose()
