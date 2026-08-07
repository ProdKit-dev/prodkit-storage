from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import DateTime, ForeignKey, Integer, String, delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, joinedload, mapped_column, relationship

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.pagination import CursorCodec, paginate_sync
from prodkit_storage.database.runtime import SyncDatabase
from prodkit_storage.database.sorting import SortRegistry
from prodkit_storage.exceptions import OutboxLeaseLostError
from prodkit_storage.models import OutboxEvent
from prodkit_storage.outbox import (
    claim_outbox_events,
    complete_outbox_event,
    enqueue_outbox_event,
)

pytestmark = pytest.mark.integration


class IntegrationBase(DeclarativeBase):
    pass


class Parent(IntegrationBase):
    __tablename__ = "storage_integration_parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    children: Mapped[list[Child]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )


class Child(IntegrationBase):
    __tablename__ = "storage_integration_children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("storage_integration_parents.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent: Mapped[Parent] = relationship(back_populates="children")


def _settings() -> StorageSettings:
    return StorageSettings(environment="test")


def test_read_only_transaction_rejects_writes() -> None:
    database = SyncDatabase(_settings())
    try:
        with pytest.raises(DBAPIError):
            with database.read_transaction() as session:
                session.execute(
                    text(
                        "UPDATE storage_outbox_events "
                        "SET attempts = attempts WHERE false"
                    )
                )
    finally:
        database.dispose()


def test_cursor_pagination_supports_joined_collection_loading() -> None:
    database = SyncDatabase(_settings())
    IntegrationBase.metadata.drop_all(database.write_engine, checkfirst=True)
    IntegrationBase.metadata.create_all(database.write_engine)
    try:
        with database.transaction() as session:
            newer = Parent(
                created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
                name="newer",
                children=[Child(name="a"), Child(name="b")],
            )
            older = Parent(
                created_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
                name="older",
                children=[Child(name="c")],
            )
            session.add_all([newer, older])

        sorting = SortRegistry(
            name="integration-parent-v1",
            fields={"created_at": Parent.created_at, "id": Parent.id},
            default=("-created_at",),
            tie_breaker="id",
        )
        with database.session() as session:
            page = paginate_sync(
                session,
                select(Parent).options(joinedload(Parent.children)),
                sort=sorting.parse(None),
                codec=CursorCodec(b"integration-cursor-secret-at-least-32"),
                limit=1,
            )
            assert [parent.name for parent in page.items] == ["newer"]
            assert len(page.items[0].children) == 2
            assert page.has_more
            assert page.next_cursor is not None
    finally:
        IntegrationBase.metadata.drop_all(database.write_engine, checkfirst=True)
        database.dispose()


def test_stale_outbox_worker_cannot_complete_reclaimed_event() -> None:
    database = SyncDatabase(_settings())
    try:
        with database.transaction() as session:
            session.execute(delete(OutboxEvent))
            event = enqueue_outbox_event(
                session,
                topic="integration",
                event_type="lease.test",
                payload={"ok": True},
            )
            session.flush()
            event_id = event.id

        with database.transaction() as session:
            first = claim_outbox_events(session, worker_id="worker-a", batch_size=1)[0]
            first_token = first.lock_token
            assert first_token is not None

        with database.transaction() as session:
            event = session.get(OutboxEvent, event_id)
            assert event is not None
            event.locked_at = datetime.now(timezone.utc) - timedelta(minutes=10)

        with database.transaction() as session:
            second = claim_outbox_events(
                session,
                worker_id="worker-b",
                batch_size=1,
                stale_after=timedelta(minutes=5),
            )[0]
            second_token = second.lock_token
            assert second_token is not None
            assert second_token != first_token

        with pytest.raises(OutboxLeaseLostError):
            with database.transaction() as session:
                complete_outbox_event(
                    session,
                    event_id=event_id,
                    lock_token=first_token,
                )

        with database.transaction() as session:
            complete_outbox_event(
                session,
                event_id=event_id,
                lock_token=second_token,
            )

        with database.session() as session:
            published = session.get(OutboxEvent, event_id)
            assert published is not None
            assert published.status == "published"
            assert published.lock_token is None
            assert published.version >= 3
    finally:
        database.dispose()
