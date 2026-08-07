"""FastAPI query and response schemas for storage pagination."""

from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

from prodkit_storage.database.pagination import CursorPage, OffsetPage

T = TypeVar("T")


class CursorPaginationParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


class OffsetPaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=500)
    include_total: bool = True


async def get_cursor_pagination(
    cursor: Annotated[str | None, Query(description="Signed continuation cursor")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> CursorPaginationParams:
    return CursorPaginationParams(cursor=cursor, limit=limit)


async def get_offset_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    include_total: bool = True,
) -> OffsetPaginationParams:
    return OffsetPaginationParams(page=page, limit=limit, include_total=include_total)


class CursorMetadata(BaseModel):
    next_cursor: str | None
    has_more: bool


class OffsetMetadata(BaseModel):
    page: int
    limit: int
    total_count: int | None
    total_pages: int | None
    has_next_page: bool
    has_previous_page: bool


class CursorListResponse(BaseModel, Generic[T]):
    items: list[T]
    pagination: CursorMetadata

    @classmethod
    def from_page(cls, page: CursorPage[T]) -> CursorListResponse[T]:
        return cls(
            items=page.items,
            pagination=CursorMetadata(
                next_cursor=page.next_cursor,
                has_more=page.has_more,
            ),
        )


class OffsetListResponse(BaseModel, Generic[T]):
    items: list[T]
    pagination: OffsetMetadata

    @classmethod
    def from_page(cls, page: OffsetPage[T]) -> OffsetListResponse[T]:
        return cls(
            items=page.items,
            pagination=OffsetMetadata(
                page=page.page,
                limit=page.limit,
                total_count=page.total_count,
                total_pages=page.total_pages,
                has_next_page=page.has_next_page,
                has_previous_page=page.has_previous_page,
            ),
        )


__all__ = [
    "CursorListResponse",
    "CursorMetadata",
    "CursorPaginationParams",
    "OffsetListResponse",
    "OffsetMetadata",
    "OffsetPaginationParams",
    "get_cursor_pagination",
    "get_offset_pagination",
]
