"""Mechanical PostgreSQL full-text-search SQLAlchemy primitives."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.sql.elements import ColumnElement


class TextQueryParser(StrEnum):
    PLAIN = "plain"
    PHRASE = "phrase"
    WEBSEARCH = "websearch"
    RAW = "raw"


def tsvector_type() -> TSVECTOR:
    """Return PostgreSQL's native ``tsvector`` SQLAlchemy type."""

    return TSVECTOR()


def to_tsvector_expression(
    document: ColumnElement[Any],
    *,
    config: str = "simple",
) -> ColumnElement[Any]:
    """Build a parameterized PostgreSQL ``to_tsvector`` expression."""

    normalized = _text_search_config(config)
    return func.to_tsvector(normalized, document)


def to_tsquery_expression(
    query: ColumnElement[Any],
    *,
    config: str = "simple",
    parser: TextQueryParser | str = TextQueryParser.WEBSEARCH,
) -> ColumnElement[Any]:
    """Build a PostgreSQL ``tsquery`` parser expression.

    ``RAW`` maps to ``to_tsquery`` and therefore expects PostgreSQL tsquery
    syntax. The other modes delegate escaping/tokenization semantics to the
    corresponding PostgreSQL parser.
    """

    normalized = _text_search_config(config)
    selected = TextQueryParser(parser)
    functions = {
        TextQueryParser.PLAIN: func.plainto_tsquery,
        TextQueryParser.PHRASE: func.phraseto_tsquery,
        TextQueryParser.WEBSEARCH: func.websearch_to_tsquery,
        TextQueryParser.RAW: func.to_tsquery,
    }
    return functions[selected](normalized, query)


def text_search_match(
    vector: ColumnElement[Any],
    query: ColumnElement[Any],
) -> ColumnElement[bool]:
    """Apply PostgreSQL's ``@@`` full-text match operator."""

    return vector.op("@@")(query)


def _text_search_config(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or any(
        not (character.isalnum() or character in {"_", "."}) for character in normalized
    ):
        raise ValueError(
            "text search config must contain only letters, digits, underscores, and dots"
        )
    return normalized


__all__ = [
    "TextQueryParser",
    "text_search_match",
    "to_tsquery_expression",
    "to_tsvector_expression",
    "tsvector_type",
]
