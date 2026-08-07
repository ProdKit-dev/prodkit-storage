"""Harden outbox dispatch leases.

Revision ID: 20260807_0002
Revises: 20260806_0001
Create Date: 2026-08-07 07:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0002"
down_revision: str | Sequence[str] | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str:
    return str(op.get_context().opts.get("version_table_schema") or "public")


def upgrade() -> None:
    schema = _schema()
    table = "storage_outbox_events"

    # Any event that was in-flight when this migration begins is made available
    # for a clean re-claim. A stale worker must not be allowed to complete it
    # after the lease model changes.
    op.execute(
        sa.text(
            f'UPDATE "{schema}".{table} '
            "SET status = 'pending', locked_at = NULL, locked_by = NULL "
            "WHERE status = 'processing'"
        )
    )
    op.add_column(
        table,
        sa.Column("version", sa.BigInteger(), server_default="1", nullable=False),
        schema=schema,
    )
    op.add_column(
        table,
        sa.Column("lock_token", sa.Uuid(), nullable=True),
        schema=schema,
    )
    # Pass the logical name; the metadata naming convention adds the
    # ck_<table>_ prefix exactly once.
    op.create_check_constraint(
        "processing_has_lock_token",
        table,
        "(status = 'processing' AND lock_token IS NOT NULL) "
        "OR (status <> 'processing' AND lock_token IS NULL)",
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    table = "storage_outbox_events"
    op.drop_constraint(
        op.f("ck_storage_outbox_events_processing_has_lock_token"),
        table,
        type_="check",
        schema=schema,
    )
    op.drop_column(table, "lock_token", schema=schema)
    op.drop_column(table, "version", schema=schema)
