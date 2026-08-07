"""Allowlisted, deterministic, multi-column SQLAlchemy sorting."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import orjson
from sqlalchemy import Select, false, or_
from sqlalchemy.sql.elements import ColumnElement


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class NullPlacement(StrEnum):
    FIRST = "first"
    LAST = "last"


Accessor = str | Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class SortField:
    name: str
    expression: ColumnElement[Any]
    accessor: Accessor | None = None
    default_nulls: NullPlacement = NullPlacement.LAST
    nullable: bool | None = None
    unique: bool | None = None

    def __post_init__(self) -> None:
        if not self.name or self.name.startswith("_"):
            raise ValueError("sort field names must be public non-empty names")
        if self.nullable is None:
            object.__setattr__(self, "nullable", bool(getattr(self.expression, "nullable", True)))
        if self.unique is None:
            object.__setattr__(
                self,
                "unique",
                bool(
                    getattr(self.expression, "unique", False)
                    or getattr(self.expression, "primary_key", False)
                ),
            )

    def value_from(self, row: Any) -> Any:
        accessor = self.accessor
        if callable(accessor):
            return accessor(row)
        attribute = accessor or getattr(self.expression, "key", None)
        if not isinstance(attribute, str) or not attribute:
            raise ValueError(
                f"sort field {self.name!r} needs an accessor for cursor pagination"
            )
        return getattr(row, attribute)


@dataclass(frozen=True, slots=True)
class SortTerm:
    field: str
    direction: SortDirection = SortDirection.ASC
    nulls: NullPlacement | None = None

    @classmethod
    def parse(cls, value: str) -> SortTerm:
        value = value.strip()
        if not value:
            raise ValueError("sorting criteria must not be empty")
        direction = SortDirection.ASC
        if value[0] in {"-", "+"}:
            direction = SortDirection.DESC if value[0] == "-" else SortDirection.ASC
            value = value[1:]
        if not value:
            raise ValueError("sorting criteria must contain a field name")
        return cls(field=value, direction=direction)

    def external_value(self) -> str:
        return f"-{self.field}" if self.direction is SortDirection.DESC else self.field


@dataclass(frozen=True, slots=True)
class ResolvedSortTerm:
    field: SortField
    direction: SortDirection
    nulls: NullPlacement

    def order_by(self) -> ColumnElement[Any]:
        ordered = (
            self.field.expression.desc()
            if self.direction is SortDirection.DESC
            else self.field.expression.asc()
        )
        return ordered.nulls_first() if self.nulls is NullPlacement.FIRST else ordered.nulls_last()

    def equality(self, cursor_value: Any) -> ColumnElement[bool]:
        if cursor_value is None:
            return self.field.expression.is_(None)
        return self.field.expression == cursor_value

    def after(self, cursor_value: Any) -> ColumnElement[bool]:
        expression = self.field.expression
        if cursor_value is None:
            return expression.is_not(None) if self.nulls is NullPlacement.FIRST else false()
        value_comparison = (
            expression < cursor_value
            if self.direction is SortDirection.DESC
            else expression > cursor_value
        )
        if self.nulls is NullPlacement.LAST:
            return or_(expression.is_(None), value_comparison)
        return value_comparison


@dataclass(frozen=True, slots=True)
class SortPlan:
    terms: tuple[ResolvedSortTerm, ...]
    fingerprint: str

    def apply(self, statement: Select[Any]) -> Select[Any]:
        return statement.order_by(*(term.order_by() for term in self.terms))

    def values_from(self, row: Any) -> tuple[Any, ...]:
        return tuple(term.field.value_from(row) for term in self.terms)

    def boundary(self, values: Sequence[Any]) -> ColumnElement[bool]:
        if len(values) != len(self.terms):
            raise ValueError("cursor value count does not match the active sorting")
        alternatives: list[tuple[ColumnElement[bool], ...]] = []
        equal_prefix: list[ColumnElement[bool]] = []
        for term, value in zip(self.terms, values, strict=True):
            alternatives.append((*equal_prefix, term.after(value)))
            equal_prefix.append(term.equality(value))
        # SQLAlchemy's and_ accepts variadic criteria; construct lazily to keep typing simple.
        from sqlalchemy import and_

        return or_(*(and_(*criteria) for criteria in alternatives))

    @property
    def external_values(self) -> tuple[str, ...]:
        return tuple(
            SortTerm(term.field.name, term.direction, term.nulls).external_value()
            for term in self.terms
        )


class SortRegistry:
    """Resolve public sort names into safe SQLAlchemy expressions."""

    def __init__(
        self,
        fields: Mapping[str, SortField | ColumnElement[Any]],
        *,
        default: Sequence[SortTerm | str],
        tie_breaker: SortTerm | str,
        name: str = "default",
    ) -> None:
        if not fields:
            raise ValueError("at least one sort field is required")
        self.name = name.strip() or "default"
        self._fields: dict[str, SortField] = {}
        for field_name, field in fields.items():
            normalized = (
                field
                if isinstance(field, SortField)
                else SortField(field_name, field)
            )
            if normalized.name != field_name:
                raise ValueError("sort field mapping key must match SortField.name")
            self._fields[field_name] = normalized
        self._default = tuple(_normalize_term(term) for term in default)
        if not self._default:
            raise ValueError("default sorting must contain at least one term")
        self._tie_breaker_was_string = isinstance(tie_breaker, str)
        self._tie_breaker = _normalize_term(tie_breaker)
        tie_field = self._require_field(self._tie_breaker.field)
        if tie_field.nullable:
            raise ValueError("the cursor tie-breaker must be non-nullable")
        if not tie_field.unique:
            raise ValueError("the cursor tie-breaker must be unique or a primary key")
        self.resolve(self._default)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._fields)

    @property
    def default(self) -> tuple[SortTerm, ...]:
        return self._default

    def parse(self, values: str | Iterable[str] | None) -> SortPlan:
        if values is None:
            return self.resolve(self._default)
        if isinstance(values, str):
            raw_values = [part for part in values.split(",") if part.strip()]
        else:
            raw_values = list(values)
        if not raw_values:
            return self.resolve(self._default)
        return self.resolve(SortTerm.parse(value) for value in raw_values)

    def resolve(self, terms: Iterable[SortTerm | str]) -> SortPlan:
        normalized = [_normalize_term(term) for term in terms]
        if not normalized:
            normalized = list(self._default)
        seen: set[str] = set()
        resolved: list[ResolvedSortTerm] = []
        for term in normalized:
            if term.field in seen:
                raise ValueError(f"duplicate sorting field: {term.field}")
            seen.add(term.field)
            field = self._require_field(term.field)
            resolved.append(
                ResolvedSortTerm(
                    field=field,
                    direction=term.direction,
                    nulls=term.nulls or field.default_nulls,
                )
            )
        if self._tie_breaker.field not in seen:
            tie_direction = self._tie_breaker.direction
            # A bare string tie-breaker is normalized to ASC; follow the last
            # criterion unless the caller supplied a full SortTerm explicitly.
            if self._tie_breaker_was_string:
                tie_direction = resolved[-1].direction
            field = self._require_field(self._tie_breaker.field)
            resolved.append(
                ResolvedSortTerm(
                    field=field,
                    direction=tie_direction,
                    nulls=self._tie_breaker.nulls or field.default_nulls,
                )
            )
        payload = [
            {
                "field": term.field.name,
                "direction": term.direction.value,
                "nulls": term.nulls.value,
            }
            for term in resolved
        ]
        fingerprint = hashlib.sha256(
            orjson.dumps({"registry": self.name, "terms": payload}, option=orjson.OPT_SORT_KEYS)
        ).hexdigest()[:24]
        return SortPlan(tuple(resolved), fingerprint)

    def _require_field(self, name: str) -> SortField:
        try:
            return self._fields[name]
        except KeyError as error:
            raise ValueError(f"unsupported sorting field: {name}") from error


def _normalize_term(term: SortTerm | str) -> SortTerm:
    return SortTerm.parse(term) if isinstance(term, str) else term


__all__ = [
    "NullPlacement",
    "ResolvedSortTerm",
    "SortDirection",
    "SortField",
    "SortPlan",
    "SortRegistry",
    "SortTerm",
]
