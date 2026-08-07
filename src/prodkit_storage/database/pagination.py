"""Signed keyset and optional offset pagination for SQLAlchemy 2.x."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Literal, TypeVar, overload
from uuid import UUID

import orjson
from sqlalchemy import Select, asc, desc, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from prodkit_storage.database.sorting import SortPlan

T = TypeVar("T")
Direction = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class CursorPage(Generic[T]):
    items: list[T]
    next_cursor: str | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class OffsetPage(Generic[T]):
    items: list[T]
    page: int
    limit: int
    total_count: int | None
    total_pages: int | None
    has_next_page: bool
    has_previous_page: bool


@dataclass(frozen=True, slots=True)
class CursorState:
    sort_fingerprint: str
    values: tuple[Any, ...]
    query_fingerprint: str | None = None


class CursorCodec:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("cursor secret must be at least 32 bytes")
        self._secret = secret

    def encode(self, position: Any, tie_breaker: Any) -> str:
        """Encode the legacy two-column cursor format."""

        return self._sign(
            {"v": 1, "p": _serialize(position), "t": _serialize(tie_breaker)}
        )

    def decode(self, token: str) -> tuple[Any, Any]:
        """Decode the legacy two-column cursor format."""

        data = self._verify(token)
        if data.get("v") != 1:
            raise ValueError("unsupported legacy cursor version")
        return data["p"], data["t"]

    def encode_state(self, state: CursorState) -> str:
        return self._sign(
            {
                "v": 2,
                "s": state.sort_fingerprint,
                "q": state.query_fingerprint,
                "values": _serialize(list(state.values)),
            }
        )

    def decode_state(self, token: str) -> CursorState:
        data = self._verify(token)
        if data.get("v") != 2:
            raise ValueError("unsupported cursor version")
        sort_fingerprint = data.get("s")
        values = data.get("values")
        query_fingerprint = data.get("q")
        if not isinstance(sort_fingerprint, str) or not isinstance(values, list):
            raise ValueError("invalid cursor payload")
        if query_fingerprint is not None and not isinstance(query_fingerprint, str):
            raise ValueError("invalid cursor query fingerprint")
        return CursorState(sort_fingerprint, tuple(values), query_fingerprint)

    def _sign(self, data: dict[str, Any]) -> str:
        payload = orjson.dumps(data, option=orjson.OPT_SORT_KEYS)
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + payload).decode("ascii").rstrip("=")

    def _verify(self, token: str) -> dict[str, Any]:
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as error:
            raise ValueError("invalid cursor encoding") from error
        if len(raw) <= hashlib.sha256().digest_size:
            raise ValueError("invalid cursor")
        signature, payload = raw[:32], raw[32:]
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid cursor signature")
        data = orjson.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("invalid cursor payload")
        return data


@overload
def paginate_sync(
    session: Session,
    statement: Select[tuple[T]],
    *,
    codec: CursorCodec,
    sort: SortPlan,
    cursor: str | None = None,
    limit: int = 50,
    query_fingerprint: str | None = None,
) -> CursorPage[T]: ...


@overload
def paginate_sync(
    session: Session,
    statement: Select[tuple[T]],
    *,
    order_column: ColumnElement[Any],
    id_column: ColumnElement[Any],
    codec: CursorCodec,
    cursor: str | None = None,
    limit: int = 50,
    direction: Direction = "desc",
) -> CursorPage[T]: ...


def paginate_sync(
    session: Session,
    statement: Select[tuple[T]],
    *,
    codec: CursorCodec,
    sort: SortPlan | None = None,
    cursor: str | None = None,
    limit: int = 50,
    query_fingerprint: str | None = None,
    order_column: ColumnElement[Any] | None = None,
    id_column: ColumnElement[Any] | None = None,
    direction: Direction = "desc",
) -> CursorPage[T]:
    if sort is not None:
        query = _prepare_sorted_query(
            statement,
            sort=sort,
            codec=codec,
            cursor=cursor,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )
        rows = list(_unique_scalars(session.scalars(query)))
        return _build_sorted_page(
            rows,
            sort=sort,
            codec=codec,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )
    if order_column is None or id_column is None:
        raise TypeError("sort or both order_column and id_column are required")
    query = _prepare_legacy_query(
        statement,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    rows = list(_unique_scalars(session.scalars(query)))
    return _build_legacy_page(
        rows,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        limit=limit,
    )


@overload
async def paginate_async(
    session: AsyncSession,
    statement: Select[tuple[T]],
    *,
    codec: CursorCodec,
    sort: SortPlan,
    cursor: str | None = None,
    limit: int = 50,
    query_fingerprint: str | None = None,
) -> CursorPage[T]: ...


@overload
async def paginate_async(
    session: AsyncSession,
    statement: Select[tuple[T]],
    *,
    order_column: ColumnElement[Any],
    id_column: ColumnElement[Any],
    codec: CursorCodec,
    cursor: str | None = None,
    limit: int = 50,
    direction: Direction = "desc",
) -> CursorPage[T]: ...


async def paginate_async(
    session: AsyncSession,
    statement: Select[tuple[T]],
    *,
    codec: CursorCodec,
    sort: SortPlan | None = None,
    cursor: str | None = None,
    limit: int = 50,
    query_fingerprint: str | None = None,
    order_column: ColumnElement[Any] | None = None,
    id_column: ColumnElement[Any] | None = None,
    direction: Direction = "desc",
) -> CursorPage[T]:
    if sort is not None:
        query = _prepare_sorted_query(
            statement,
            sort=sort,
            codec=codec,
            cursor=cursor,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )
        result = await session.scalars(query)
        rows = list(_unique_scalars(result))
        return _build_sorted_page(
            rows,
            sort=sort,
            codec=codec,
            limit=limit,
            query_fingerprint=query_fingerprint,
        )
    if order_column is None or id_column is None:
        raise TypeError("sort or both order_column and id_column are required")
    query = _prepare_legacy_query(
        statement,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    result = await session.scalars(query)
    rows = list(_unique_scalars(result))
    return _build_legacy_page(
        rows,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        limit=limit,
    )


def paginate_offset_sync(
    session: Session,
    statement: Select[tuple[T]],
    *,
    page: int = 1,
    limit: int = 50,
    include_total: bool = True,
    count_statement: Select[Any] | None = None,
) -> OffsetPage[T]:
    _validate_offset(page, limit)
    total_count = (
        _count_sync(session, statement, count_statement=count_statement)
        if include_total
        else None
    )
    fetch_limit = limit if include_total else limit + 1
    result = session.scalars(statement.offset((page - 1) * limit).limit(fetch_limit))
    rows = list(_unique_scalars(result))
    has_next_page = (
        page < math.ceil(total_count / limit)
        if total_count is not None
        else len(rows) > limit
    )
    return _offset_page(rows[:limit], page, limit, total_count, has_next_page)


async def paginate_offset_async(
    session: AsyncSession,
    statement: Select[tuple[T]],
    *,
    page: int = 1,
    limit: int = 50,
    include_total: bool = True,
    count_statement: Select[Any] | None = None,
) -> OffsetPage[T]:
    _validate_offset(page, limit)
    total_count = (
        await _count_async(session, statement, count_statement=count_statement)
        if include_total
        else None
    )
    fetch_limit = limit if include_total else limit + 1
    result = await session.scalars(
        statement.offset((page - 1) * limit).limit(fetch_limit)
    )
    rows = list(_unique_scalars(result))
    has_next_page = (
        page < math.ceil(total_count / limit)
        if total_count is not None
        else len(rows) > limit
    )
    return _offset_page(rows[:limit], page, limit, total_count, has_next_page)


def count_subquery(statement: Select[Any]) -> Subquery:
    """Build a correctness-first count subquery with ordering removed.

    The original projection is retained so ``DISTINCT`` and grouped statements
    keep their semantics. Callers with joined collection queries can supply an
    explicit count statement to the offset paginator.
    """

    return statement.order_by(None).subquery()


def _count_sync(
    session: Session,
    statement: Select[Any],
    *,
    count_statement: Select[Any] | None,
) -> int:
    query = (
        count_statement
        if count_statement is not None
        else select(func.count()).select_from(count_subquery(statement))
    )
    count = session.scalar(query)
    return int(count or 0)


async def _count_async(
    session: AsyncSession,
    statement: Select[Any],
    *,
    count_statement: Select[Any] | None,
) -> int:
    query = (
        count_statement
        if count_statement is not None
        else select(func.count()).select_from(count_subquery(statement))
    )
    count = await session.scalar(query)
    return int(count or 0)


def _prepare_sorted_query(
    statement: Select[tuple[T]],
    *,
    sort: SortPlan,
    codec: CursorCodec,
    cursor: str | None,
    limit: int,
    query_fingerprint: str | None,
) -> Select[tuple[T]]:
    _validate_limit(limit)
    query = statement
    if cursor is not None:
        state = codec.decode_state(cursor)
        if state.sort_fingerprint != sort.fingerprint:
            raise ValueError("cursor sorting does not match the active sorting")
        if state.query_fingerprint != query_fingerprint:
            raise ValueError("cursor query does not match the active query")
        if len(state.values) != len(sort.terms):
            raise ValueError("cursor value count does not match the active sorting")
        values = tuple(
            _coerce(term.field.expression, value)
            for term, value in zip(sort.terms, state.values, strict=True)
        )
        query = query.where(sort.boundary(values))
    return sort.apply(query).limit(limit + 1)


def _build_sorted_page(
    rows: list[T],
    *,
    sort: SortPlan,
    codec: CursorCodec,
    limit: int,
    query_fingerprint: str | None,
) -> CursorPage[T]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        next_cursor = codec.encode_state(
            CursorState(
                sort_fingerprint=sort.fingerprint,
                values=tuple(sort.values_from(items[-1])),
                query_fingerprint=query_fingerprint,
            )
        )
    return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _prepare_legacy_query(
    statement: Select[tuple[T]],
    *,
    order_column: ColumnElement[Any],
    id_column: ColumnElement[Any],
    codec: CursorCodec,
    cursor: str | None,
    limit: int,
    direction: Direction,
) -> Select[tuple[T]]:
    _validate_limit(limit)
    if direction not in {"asc", "desc"}:
        raise ValueError("direction must be 'asc' or 'desc'")
    query = statement
    if cursor is not None:
        position, tie_breaker = codec.decode(cursor)
        position = _coerce(order_column, position)
        tie_breaker = _coerce(id_column, tie_breaker)
        boundary = tuple_(order_column, id_column)
        values = tuple_(position, tie_breaker)
        query = query.where(boundary < values if direction == "desc" else boundary > values)
    ordering = desc if direction == "desc" else asc
    return query.order_by(ordering(order_column), ordering(id_column)).limit(limit + 1)


def _build_legacy_page(
    rows: list[T],
    *,
    order_column: ColumnElement[Any],
    id_column: ColumnElement[Any],
    codec: CursorCodec,
    limit: int,
) -> CursorPage[T]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        order_attribute = _mapped_attribute_name(order_column, "order_column")
        id_attribute = _mapped_attribute_name(id_column, "id_column")
        next_cursor = codec.encode(getattr(last, order_attribute), getattr(last, id_attribute))
    return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _offset_page(
    items: list[T],
    page: int,
    limit: int,
    total_count: int | None,
    has_next_page: bool,
) -> OffsetPage[T]:
    total_pages = math.ceil(total_count / limit) if total_count is not None else None
    return OffsetPage(
        items=items,
        page=page,
        limit=limit,
        total_count=total_count,
        total_pages=total_pages,
        has_next_page=has_next_page,
        has_previous_page=page > 1,
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")


def _validate_offset(page: int, limit: int) -> None:
    if page < 1:
        raise ValueError("page must be positive")
    _validate_limit(limit)


def _unique_scalars(result: Any) -> Any:
    unique = getattr(result, "unique", None)
    return unique().all() if callable(unique) else result.all()


def _serialize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _serialize(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _coerce(column: ColumnElement[Any], value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if python_type is UUID:
        return UUID(value)
    if python_type is datetime:
        return datetime.fromisoformat(value)
    if python_type is date:
        return date.fromisoformat(value)
    if isinstance(python_type, type) and issubclass(python_type, Enum):
        return python_type(value)
    return python_type(value)


def _mapped_attribute_name(column: ColumnElement[Any], argument: str) -> str:
    key = getattr(column, "key", None)
    if not isinstance(key, str) or not key:
        raise ValueError(f"{argument} must be a mapped column with an attribute key")
    return key


__all__ = [
    "CursorCodec",
    "CursorPage",
    "CursorState",
    "OffsetPage",
    "count_subquery",
    "paginate_async",
    "paginate_offset_async",
    "paginate_offset_sync",
    "paginate_sync",
]
