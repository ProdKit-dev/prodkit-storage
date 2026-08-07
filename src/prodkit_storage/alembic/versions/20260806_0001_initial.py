"""Create storage infrastructure tables and extensions.

Revision ID: 20260806_0001
Revises:
Create Date: 2026-08-06 08:09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str:
    return str(op.get_context().opts.get("version_table_schema") or "public")


def upgrade() -> None:
    schema = _schema()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "storage_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=1024), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storage_audit_events"),
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_actor_id",
        "storage_audit_events",
        ["actor_id"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_tenant_id",
        "storage_audit_events",
        ["tenant_id"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_entity",
        "storage_audit_events",
        ["entity_type", "entity_id", "occurred_at"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_tenant_time",
        "storage_audit_events",
        ["tenant_id", "occurred_at"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_request_id",
        "storage_audit_events",
        ["request_id"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_audit_events_metadata_gin",
        "storage_audit_events",
        ["metadata"],
        postgresql_using="gin",
        schema=schema,
    )

    op.create_table(
        "storage_outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=True),
        sa.Column("aggregate_id", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'published', 'dead')",
            name="status",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_storage_outbox_events"),
        schema=schema,
    )
    op.create_index(
        "ix_storage_outbox_events_tenant_id",
        "storage_outbox_events",
        ["tenant_id"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_outbox_events_dispatch",
        "storage_outbox_events",
        ["status", "available_at", "created_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        schema=schema,
    )
    op.create_index(
        "ix_storage_outbox_events_aggregate",
        "storage_outbox_events",
        ["aggregate_type", "aggregate_id"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_outbox_events_tenant_created",
        "storage_outbox_events",
        ["tenant_id", "created_at"],
        schema=schema,
    )
    op.create_index(
        "ix_storage_outbox_events_payload_gin",
        "storage_outbox_events",
        ["payload"],
        postgresql_using="gin",
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_index("ix_storage_outbox_events_payload_gin", table_name="storage_outbox_events", schema=schema)
    op.drop_index("ix_storage_outbox_events_tenant_created", table_name="storage_outbox_events", schema=schema)
    op.drop_index("ix_storage_outbox_events_aggregate", table_name="storage_outbox_events", schema=schema)
    op.drop_index("ix_storage_outbox_events_dispatch", table_name="storage_outbox_events", schema=schema)
    op.drop_index("ix_storage_outbox_events_tenant_id", table_name="storage_outbox_events", schema=schema)
    op.drop_table("storage_outbox_events", schema=schema)

    op.drop_index("ix_storage_audit_events_metadata_gin", table_name="storage_audit_events", schema=schema)
    op.drop_index("ix_storage_audit_events_request_id", table_name="storage_audit_events", schema=schema)
    op.drop_index("ix_storage_audit_events_tenant_time", table_name="storage_audit_events", schema=schema)
    op.drop_index("ix_storage_audit_events_entity", table_name="storage_audit_events", schema=schema)
    op.drop_index("ix_storage_audit_events_tenant_id", table_name="storage_audit_events", schema=schema)
    op.drop_index("ix_storage_audit_events_actor_id", table_name="storage_audit_events", schema=schema)
    op.drop_table("storage_audit_events", schema=schema)
    # Extensions are intentionally retained because other application schemas may use them.
