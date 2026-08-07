from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from prodkit_storage.database.base import Base, UUIDPrimaryKeyMixin
from prodkit_storage.database.filtering import (
    FilterField,
    FilterOperator,
    FilterRegistry,
    FilterTerm,
)
from prodkit_storage.database.pagination import CursorCodec, paginate_sync
from prodkit_storage.database.sorting import (
    NullPlacement,
    SortDirection,
    SortField,
    SortRegistry,
    SortTerm,
)
from prodkit_storage.models import OutboxEvent


class SortCustomer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "test_sort_customers"

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class PageSession:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statement: Any = None

    def scalars(self, statement: Any) -> ScalarRows:
        self.statement = statement
        return ScalarRows(self.rows)


def event(identifier: str, created_at: datetime) -> OutboxEvent:
    return OutboxEvent(
        id=UUID(identifier),
        topic="events",
        event_type="created",
        payload={},
        created_at=created_at,
        available_at=created_at,
    )


def outbox_sort_registry() -> SortRegistry:
    return SortRegistry(
        fields={
            "created_at": SortField("created_at", OutboxEvent.created_at),
            "id": SortField("id", OutboxEvent.id),
        },
        default=(SortTerm("created_at", SortDirection.DESC),),
        tie_breaker="id",
        name="outbox",
    )


def test_sort_registry_is_allowlisted_stable_and_null_explicit() -> None:
    registry = SortRegistry(
        fields={
            "name": SortField(
                "name",
                SortCustomer.name,
                default_nulls=NullPlacement.LAST,
            ),
            "id": SortField("id", SortCustomer.id),
        },
        default=("name",),
        tie_breaker="id",
        name="customers",
    )
    plan = registry.parse(["-name"])
    assert [term.field.name for term in plan.terms] == ["name", "id"]
    assert [term.direction for term in plan.terms] == [
        SortDirection.DESC,
        SortDirection.DESC,
    ]
    assert plan.terms[0].nulls is NullPlacement.LAST
    sql = str(
        plan.apply(select(SortCustomer)).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "ORDER BY" in sql
    assert "name DESC NULLS LAST" in sql
    assert "id DESC NULLS LAST" in sql

    with pytest.raises(ValueError, match="unsupported"):
        registry.parse(["secret_column"])
    with pytest.raises(ValueError, match="duplicate"):
        registry.parse(["name", "-name"])


def test_sorted_cursor_binds_sort_and_query_fingerprints() -> None:
    first = event(
        "00000000-0000-0000-0000-000000000002",
        datetime(2026, 8, 6, tzinfo=timezone.utc),
    )
    second = event(
        "00000000-0000-0000-0000-000000000001",
        datetime(2026, 8, 5, tzinfo=timezone.utc),
    )
    codec = CursorCodec(b"s" * 32)
    registry = outbox_sort_registry()
    plan = registry.parse(None)
    page = paginate_sync(
        PageSession([first, second]),  # type: ignore[arg-type]
        select(OutboxEvent),
        sort=plan,
        codec=codec,
        limit=1,
        query_fingerprint="tenant:1",
    )
    assert page.items == [first]
    assert page.next_cursor is not None
    state = codec.decode_state(page.next_cursor)
    assert state.sort_fingerprint == plan.fingerprint
    assert state.query_fingerprint == "tenant:1"
    assert state.values[0] == "2026-08-06T00:00:00+00:00"

    follow_up = PageSession([second])
    next_page = paginate_sync(
        follow_up,  # type: ignore[arg-type]
        select(OutboxEvent),
        sort=plan,
        codec=codec,
        cursor=page.next_cursor,
        limit=1,
        query_fingerprint="tenant:1",
    )
    assert next_page.items == [second]
    assert "WHERE" in str(follow_up.statement)

    with pytest.raises(ValueError, match="sorting"):
        paginate_sync(
            PageSession([]),  # type: ignore[arg-type]
            select(OutboxEvent),
            sort=registry.parse(["created_at"]),
            codec=codec,
            cursor=page.next_cursor,
            query_fingerprint="tenant:1",
        )
    with pytest.raises(ValueError, match="query"):
        paginate_sync(
            PageSession([]),  # type: ignore[arg-type]
            select(OutboxEvent),
            sort=plan,
            codec=codec,
            cursor=page.next_cursor,
            query_fingerprint="tenant:2",
        )


def test_filter_registry_applies_only_declared_operators() -> None:
    registry = FilterRegistry(
        {
            "status": FilterField(
                "status",
                SortCustomer.status,
                frozenset({FilterOperator.EQ, FilterOperator.IN}),
            ),
            "name": FilterField(
                "name",
                SortCustomer.name,
                frozenset({FilterOperator.CONTAINS, FilterOperator.IS_NULL}),
            ),
        }
    )
    statement = registry.apply(
        select(SortCustomer),
        [
            FilterTerm("status", FilterOperator.IN, ["active", "trial"]),
            FilterTerm("name", FilterOperator.IS_NULL, False),
        ],
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "status IN" in sql
    assert "name IS NOT NULL" in sql

    with pytest.raises(ValueError, match="not allowed"):
        registry.resolve([FilterTerm("status", FilterOperator.CONTAINS, "x")])
    with pytest.raises(ValueError, match="non-string sequence"):
        registry.resolve([FilterTerm("status", FilterOperator.IN, "active")])
    with pytest.raises(ValueError, match="string value"):
        registry.resolve([FilterTerm("name", FilterOperator.CONTAINS, 42)])

    escaped = registry.apply(
        select(SortCustomer),
        [FilterTerm("name", FilterOperator.CONTAINS, "a%b_c/d")],
    )
    escaped_sql = str(
        escaped.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "a/%%b/_c//d" in escaped_sql
    assert "ESCAPE '/'" in escaped_sql


def test_count_subquery_preserves_distinct_semantics() -> None:
    from prodkit_storage.database.pagination import count_subquery

    statement = select(SortCustomer.status).distinct().order_by(SortCustomer.status)
    compiled = str(
        count_subquery(statement).select().compile(dialect=postgresql.dialect())
    )
    assert "DISTINCT" in compiled
    assert "ORDER BY" not in compiled


def test_filter_field_mapping_name_must_match() -> None:
    with pytest.raises(ValueError, match="mapping key"):
        FilterRegistry(
            {
                "status": FilterField(
                    "different",
                    SortCustomer.status,
                    frozenset({FilterOperator.EQ}),
                )
            }
        )
