"""Small PostgreSQL JSONB expression helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, literal
from sqlalchemy.sql.elements import ColumnElement


def jsonb_text_path(
    expression: ColumnElement[Any],
    *path: str,
) -> ColumnElement[Any]:
    """Extract a nested JSONB value as text using bound path components."""

    if not path:
        raise ValueError("at least one JSONB path component is required")
    normalized = tuple(_path_component(component) for component in path)
    path_arguments = tuple(literal(component) for component in normalized)
    return func.jsonb_extract_path_text(expression, *path_arguments)


def jsonb_array_or_scalar(expression: ColumnElement[Any]) -> ColumnElement[Any]:
    """Normalize a JSONB scalar/object value to a one-element JSONB array.

    Existing arrays are returned unchanged. This is useful for generic LATERAL
    expansion without imposing application-specific filtering or sorting rules.
    """

    return case(
        (func.jsonb_typeof(expression) == "array", expression),
        else_=func.jsonb_build_array(expression),
    )


def _path_component(value: str) -> str:
    if not value:
        raise ValueError("JSONB path components must not be empty")
    if "\x00" in value:
        raise ValueError("JSONB path components must not contain NUL bytes")
    return value


__all__ = ["jsonb_array_or_scalar", "jsonb_text_path"]
