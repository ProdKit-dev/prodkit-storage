"""Signed keyset pagination with deterministic tie-breaking."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

import orjson
from sqlalchemy import Select, asc, desc, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

T = TypeVar("T")
Direction = Literal["asc", "desc"]


@dataclass(frozen=True, slots=True)
class CursorPage(Generic[T]):
    items: list[T]
    next_cursor: str | None
    has_more: bool


class CursorCodec:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("cursor secret must be at least 32 bytes")
        self._secret = secret

    def encode(self, position: Any, tie_breaker: Any) -> str:
        payload = orjson.dumps(
            {"v": 1, "p": _serialize(position), "t": _serialize(tie_breaker)},
            option=orjson.OPT_SORT_KEYS,
        )
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + payload).decode("ascii").rstrip("=")

    def decode(self, token: str) -> tuple[Any, Any]:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(raw) <= hashlib.sha256().digest_size:
            raise ValueError("invalid cursor")
        signature, payload = raw[:32], raw[32:]
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid cursor signature")
        data = orjson.loads(payload)
        if data.get("v") != 1:
            raise ValueError("unsupported cursor version")
        return data["p"], data["t"]


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
) -> CursorPage[T]:
    query = _prepare_query(
        statement,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    rows = list(session.scalars(query).all())
    return _build_page(
        rows,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        limit=limit,
    )


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
) -> CursorPage[T]:
    query = _prepare_query(
        statement,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        cursor=cursor,
        limit=limit,
        direction=direction,
    )
    result = await session.scalars(query)
    rows = list(result.all())
    return _build_page(
        rows,
        order_column=order_column,
        id_column=id_column,
        codec=codec,
        limit=limit,
    )


def _prepare_query(
    statement: Select[tuple[T]],
    *,
    order_column: ColumnElement[Any],
    id_column: ColumnElement[Any],
    codec: CursorCodec,
    cursor: str | None,
    limit: int,
    direction: Direction,
) -> Select[tuple[T]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
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


def _build_page(
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
        order_key = getattr(last, order_attribute)
        id_key = getattr(last, id_attribute)
        next_cursor = codec.encode(order_key, id_key)
    return CursorPage(items=items, next_cursor=next_cursor, has_more=has_more)


def _serialize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _coerce(column: ColumnElement[Any], value: Any) -> Any:
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
    return python_type(value)


def _mapped_attribute_name(column: ColumnElement[Any], argument: str) -> str:
    key = getattr(column, "key", None)
    if not isinstance(key, str) or not key:
        raise ValueError(f"{argument} must be a mapped column with an attribute key")
    return key
