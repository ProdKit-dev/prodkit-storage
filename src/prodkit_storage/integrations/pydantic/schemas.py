"""Pydantic schemas and validators aligned with PostgreSQL constraints."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from annotated_types import Ge, Le
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


class StorageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def _reject_nul_characters(cls, value: Any) -> Any:
        reject_nul_characters(value)
        return value


class IDSchema(StorageSchema):
    id: UUID = Field(description="Persistent object identifier.")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_mode_override="serialization",
    )


class TimestampedSchema(StorageSchema):
    created_at: datetime
    updated_at: datetime


def reject_nul_characters(value: Any) -> None:
    pending = [value]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if "\x00" in current:
                raise ValueError("value contains a PostgreSQL-incompatible NUL character")
            continue
        if isinstance(current, BaseModel):
            pending.extend(current.__dict__.values())
            continue
        if isinstance(current, Mapping):
            if id(current) in visited:
                continue
            visited.add(id(current))
            pending.extend(current.keys())
            pending.extend(current.values())
            continue
        if isinstance(current, Collection) and not isinstance(
            current, (bytes, bytearray)
        ):
            if id(current) in visited:
                continue
            visited.add(id(current))
            pending.extend(current)


def _no_nul(value: str) -> str:
    reject_nul_characters(value)
    return value


def _trim(value: str) -> str:
    return value.strip()


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


NoNulString = Annotated[str, AfterValidator(_no_nul)]
TrimmedString = Annotated[str, AfterValidator(_trim), AfterValidator(_no_nul)]
EmptyStringToNone = Annotated[
    str | None,
    AfterValidator(_empty_to_none),
    AfterValidator(lambda value: _no_nul(value) if value is not None else None),
]
PostgresInt16 = Annotated[int, Ge(-32_768), Le(32_767)]
PostgresInt32 = Annotated[int, Ge(-2_147_483_648), Le(2_147_483_647)]
PostgresInt64 = Annotated[
    int,
    Ge(-9_223_372_036_854_775_808),
    Le(9_223_372_036_854_775_807),
]


__all__ = [
    "EmptyStringToNone",
    "IDSchema",
    "NoNulString",
    "PostgresInt16",
    "PostgresInt32",
    "PostgresInt64",
    "StorageSchema",
    "TimestampedSchema",
    "TrimmedString",
    "reject_nul_characters",
]
