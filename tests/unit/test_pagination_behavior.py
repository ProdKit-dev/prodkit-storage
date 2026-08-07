from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import literal, select, text

from prodkit_storage.database.pagination import (
    CursorCodec,
    _coerce,
    _mapped_attribute_name,
    paginate_async,
    paginate_sync,
)
from prodkit_storage.models import OutboxEvent


class ScalarRows:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self.rows = rows

    def all(self) -> list[OutboxEvent]:
        return self.rows


class SyncPageSession:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self.rows = rows
        self.statement: Any = None

    def scalars(self, statement: Any) -> ScalarRows:
        self.statement = statement
        return ScalarRows(self.rows)


class AsyncPageSession(SyncPageSession):
    async def scalars(self, statement: Any) -> ScalarRows:
        return super().scalars(statement)


def make_event(identifier: str, created_at: datetime) -> OutboxEvent:
    return OutboxEvent(
        id=UUID(identifier),
        topic="events",
        event_type="created",
        payload={},
        created_at=created_at,
        available_at=created_at,
    )


def test_sync_signed_keyset_pagination_and_cursor_boundary() -> None:
    first = make_event(
        "00000000-0000-0000-0000-000000000002",
        datetime(2026, 8, 6, tzinfo=timezone.utc),
    )
    second = make_event(
        "00000000-0000-0000-0000-000000000001",
        datetime(2026, 8, 5, tzinfo=timezone.utc),
    )
    codec = CursorCodec(b"x" * 32)
    session = SyncPageSession([first, second])

    page = paginate_sync(
        session,  # type: ignore[arg-type]
        select(OutboxEvent),
        order_column=OutboxEvent.created_at,
        id_column=OutboxEvent.id,
        codec=codec,
        limit=1,
    )
    assert page.items == [first]
    assert page.has_more and page.next_cursor
    position, identifier = codec.decode(page.next_cursor)
    assert position == "2026-08-06T00:00:00+00:00"
    assert identifier == str(first.id)

    follow_up = SyncPageSession([second])
    page_two = paginate_sync(
        follow_up,  # type: ignore[arg-type]
        select(OutboxEvent),
        order_column=OutboxEvent.created_at,
        id_column=OutboxEvent.id,
        codec=codec,
        cursor=page.next_cursor,
        limit=1,
    )
    assert page_two.items == [second]
    assert not page_two.has_more and page_two.next_cursor is None


@pytest.mark.asyncio
async def test_async_pagination_and_validation() -> None:
    event = make_event("00000000-0000-0000-0000-000000000001", datetime.now(timezone.utc))
    page = await paginate_async(
        AsyncPageSession([event]),  # type: ignore[arg-type]
        select(OutboxEvent),
        order_column=OutboxEvent.created_at,
        id_column=OutboxEvent.id,
        codec=CursorCodec(b"x" * 32),
        direction="asc",
    )
    assert page.items == [event]

    with pytest.raises(ValueError, match="limit"):
        paginate_sync(
            SyncPageSession([]),  # type: ignore[arg-type]
            select(OutboxEvent),
            order_column=OutboxEvent.created_at,
            id_column=OutboxEvent.id,
            codec=CursorCodec(b"x" * 32),
            limit=0,
        )
    with pytest.raises(ValueError, match="direction"):
        paginate_sync(
            SyncPageSession([]),  # type: ignore[arg-type]
            select(OutboxEvent),
            order_column=OutboxEvent.created_at,
            id_column=OutboxEvent.id,
            codec=CursorCodec(b"x" * 32),
            direction="sideways",  # type: ignore[arg-type]
        )


def test_cursor_coercion_and_mapped_column_validation() -> None:
    identifier = UUID("00000000-0000-0000-0000-000000000001")
    instant = datetime(2026, 8, 6, tzinfo=timezone.utc)
    day = date(2026, 8, 6)
    assert _coerce(OutboxEvent.id, str(identifier)) == identifier
    assert _coerce(OutboxEvent.created_at, instant.isoformat()) == instant
    assert _coerce(literal(day), day.isoformat()) == day
    assert _mapped_attribute_name(OutboxEvent.id, "id") == "id"
    with pytest.raises(ValueError, match="mapped column"):
        _mapped_attribute_name(text("now()"), "value")
