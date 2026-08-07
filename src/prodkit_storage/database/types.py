"""Portable SQLAlchemy enum types with explicit storage semantics."""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, TypeVar

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

EnumT = TypeVar("EnumT", bound=Enum)


class _EnumType(TypeDecorator[EnumT], Generic[EnumT]):
    cache_ok = True

    def __init__(self, enum_class: type[EnumT], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.enum_class = enum_class

    @property
    def python_type(self) -> type[EnumT]:
        return self.enum_class

    def process_result_value(self, value: Any, dialect: Dialect) -> EnumT | None:
        del dialect
        if value is None or isinstance(value, self.enum_class):
            return value
        return self.enum_class(value)

    def _member(self, raw: Any) -> EnumT:
        try:
            return self.enum_class(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{raw!r} is not a valid value for {self.enum_class.__name__}"
            ) from error


class StringEnumType(_EnumType[EnumT]):
    """Store an enum's value in a portable VARCHAR column."""

    impl = String

    def __init__(
        self,
        enum_class: type[EnumT],
        *,
        length: int | None = None,
    ) -> None:
        values = [member.value for member in enum_class]
        if any(not isinstance(value, str) for value in values):
            raise TypeError("StringEnumType requires string-valued enum members")
        inferred = max((len(value) for value in values), default=1)
        selected_length = length or inferred
        if selected_length < inferred:
            raise ValueError("length is smaller than the longest enum value")
        self.length = selected_length
        super().__init__(enum_class)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        return dialect.type_descriptor(String(self.length))

    def process_bind_param(self, value: EnumT | str | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        raw = value.value if isinstance(value, self.enum_class) else value
        if not isinstance(raw, str):
            raise TypeError("StringEnumType values must be strings")
        member = self._member(raw)
        return str(member.value)


class IntegerEnumType(_EnumType[EnumT]):
    """Store an enum's value in a portable INTEGER column."""

    impl = Integer

    def __init__(self, enum_class: type[EnumT]) -> None:
        if any(not isinstance(member.value, int) for member in enum_class):
            raise TypeError("IntegerEnumType requires integer-valued enum members")
        super().__init__(enum_class)

    def process_bind_param(self, value: EnumT | int | None, dialect: Dialect) -> int | None:
        del dialect
        if value is None:
            return None
        raw = value.value if isinstance(value, self.enum_class) else value
        if not isinstance(raw, int):
            raise TypeError("IntegerEnumType values must be integers")
        member = self._member(raw)
        return int(member.value)


def postgres_enum_type(
    enum_class: type[EnumT],
    *,
    name: str,
    schema: str | None = None,
    create_type: bool = True,
) -> ENUM:
    """Create an explicit PostgreSQL native enum type.

    Native enums should be an intentional migration decision. The portable
    string type is easier to evolve for most SaaS status fields.
    """

    return ENUM(
        enum_class,
        name=name,
        schema=schema,
        native_enum=True,
        create_constraint=False,
        values_callable=lambda enum: [str(member.value) for member in enum],
        create_type=create_type,
    )


__all__ = ["IntegerEnumType", "StringEnumType", "postgres_enum_type"]
