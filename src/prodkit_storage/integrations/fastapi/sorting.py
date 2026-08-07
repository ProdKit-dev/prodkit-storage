"""FastAPI adapter for allowlisted storage sorting."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import HTTPException, Query, status

from prodkit_storage.database.sorting import SortPlan, SortRegistry

SortingDependency = Callable[..., Awaitable[SortPlan]]


def create_sorting_dependency(registry: SortRegistry) -> SortingDependency:
    allowed = ", ".join(registry.names)
    description = (
        "Sorting criteria applied in order. Prefix a field with '-' for descending order. "
        f"Allowed fields: {allowed}."
    )

    async def get_sorting(
        sorting: Annotated[
            list[str] | None,
            Query(description=description, alias="sort"),
        ] = None,
    ) -> SortPlan:
        try:
            return registry.parse(sorting)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    return get_sorting


__all__ = ["SortingDependency", "create_sorting_dependency"]
