from __future__ import annotations

from prodkit_storage.database.migration_safety import (
    MigrationSeverity,
    inspect_migration_source,
)
from prodkit_storage.database.schema_compatibility import (
    STORAGE_SCHEMA_HEAD,
    SchemaCompatibilityPolicy,
    SchemaRevisionState,
    evaluate_schema_revisions,
)


def test_migration_linter_allows_new_table_bootstrap_operations() -> None:
    report = inspect_migration_source(
        """
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table("widgets", sa.Column("id", sa.Integer(), primary_key=True))
    op.create_index("ix_widgets_id", "widgets", ["id"])
"""
    )
    assert report.safe
    assert report.issues == ()


def test_migration_linter_blocks_existing_table_index_without_concurrently() -> None:
    report = inspect_migration_source(
        """
from alembic import op

def upgrade():
    op.create_index("ix_orders_created", "orders", ["created_at"])
"""
    )
    assert not report.safe
    assert report.blocking_issues[0].code == "blocking-index"


def test_migration_linter_accepts_concurrent_index_in_autocommit_block() -> None:
    report = inspect_migration_source(
        """
from alembic import op

def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_orders_created",
            "orders",
            ["created_at"],
            postgresql_concurrently=True,
        )
"""
    )
    assert report.safe


def test_migration_linter_keeps_explicit_waivers_visible() -> None:
    report = inspect_migration_source(
        """
from alembic import op

migration_safety_allow = {"destructive-change"}

def upgrade():
    op.drop_column("orders", "legacy")
"""
    )
    assert report.safe
    assert report.issues[0].severity is MigrationSeverity.ERROR
    assert report.issues[0].code in report.waivers


def test_schema_compatibility_contract_is_explicit() -> None:
    current = evaluate_schema_revisions((STORAGE_SCHEMA_HEAD,))
    assert current.compatible
    assert current.state is SchemaRevisionState.CURRENT

    policy = SchemaCompatibilityPolicy(
        expected_revision="rev-3",
        compatible_revisions=frozenset({"rev-2", "rev-3"}),
        compatibility_version=2,
    )
    compatible = evaluate_schema_revisions(("rev-2",), policy=policy)
    assert compatible.compatible
    assert compatible.state is SchemaRevisionState.COMPATIBLE
    assert compatible.compatibility_version == 2

    incompatible = evaluate_schema_revisions(("rev-1",), policy=policy)
    assert not incompatible.compatible
    assert incompatible.state is SchemaRevisionState.INCOMPATIBLE

    multiple = evaluate_schema_revisions(("rev-2", "branch-head"), policy=policy)
    assert multiple.state is SchemaRevisionState.MULTIPLE_HEADS
