"""Typed, allowlisted SQLAlchemy filtering primitives."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import Select
from sqlalchemy.sql.elements import ColumnElement


class FilterOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


@dataclass(frozen=True, slots=True)
class FilterField:
    name: str
    expression: ColumnElement[Any]
    operators: frozenset[FilterOperator] = frozenset({FilterOperator.EQ})

    def __post_init__(self) -> None:
        if not self.name or self.name.startswith("_"):
            raise ValueError("filter field names must be public non-empty names")
        if not self.operators:
            raise ValueError("filter fields must allow at least one operator")


@dataclass(frozen=True, slots=True)
class FilterTerm:
    field: str
    operator: FilterOperator
    value: Any = None


class FilterRegistry:
    def __init__(self, fields: Mapping[str, FilterField | ColumnElement[Any]]) -> None:
        if not fields:
            raise ValueError("at least one filter field is required")
        normalized: dict[str, FilterField] = {}
        for name, field in fields.items():
            if not name or name.startswith("_"):
                raise ValueError("filter field names must be public non-empty names")
            normalized_field = field if isinstance(field, FilterField) else FilterField(name, field)
            if normalized_field.name != name:
                raise ValueError("filter field mapping key must match FilterField.name")
            normalized[name] = normalized_field
        self._fields = normalized

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._fields)

    def resolve(self, terms: Iterable[FilterTerm]) -> tuple[ColumnElement[bool], ...]:
        return tuple(self._resolve_term(term) for term in terms)

    def apply(self, statement: Select[Any], terms: Iterable[FilterTerm]) -> Select[Any]:
        criteria = self.resolve(terms)
        return statement.where(*criteria) if criteria else statement

    def _resolve_term(self, term: FilterTerm) -> ColumnElement[bool]:
        try:
            field = self._fields[term.field]
        except KeyError as error:
            raise ValueError(f"unsupported filter field: {term.field}") from error
        if term.operator not in field.operators:
            raise ValueError(
                f"operator {term.operator.value!r} is not allowed for {term.field!r}"
            )
        expression = field.expression
        value = term.value
        match term.operator:
            case FilterOperator.EQ:
                result = expression == value
            case FilterOperator.NE:
                result = expression != value
            case FilterOperator.LT:
                result = expression < value
            case FilterOperator.LTE:
                result = expression <= value
            case FilterOperator.GT:
                result = expression > value
            case FilterOperator.GTE:
                result = expression >= value
            case FilterOperator.IN:
                result = expression.in_(_require_sequence(value, term.operator))
            case FilterOperator.NOT_IN:
                result = expression.not_in(_require_sequence(value, term.operator))
            case FilterOperator.IS_NULL:
                if not isinstance(value, bool):
                    raise ValueError("is_null filter requires a boolean value")
                result = expression.is_(None) if value else expression.is_not(None)
            case FilterOperator.CONTAINS:
                result = expression.contains(
                    _require_string(value, term.operator), autoescape=True
                )
            case FilterOperator.STARTS_WITH:
                result = expression.startswith(
                    _require_string(value, term.operator), autoescape=True
                )
            case FilterOperator.ENDS_WITH:
                result = expression.endswith(
                    _require_string(value, term.operator), autoescape=True
                )
            case _:
                raise AssertionError("unreachable")
        return cast(ColumnElement[bool], result)


def _require_sequence(value: Any, operator: FilterOperator) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{operator.value} filter requires a non-string sequence")
    return value


def _require_string(value: Any, operator: FilterOperator) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{operator.value} filter requires a string value")
    return value


__all__ = ["FilterField", "FilterOperator", "FilterRegistry", "FilterTerm"]
