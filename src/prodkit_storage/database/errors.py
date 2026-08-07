"""PostgreSQL error classification across psycopg and asyncpg wrappers."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy.exc import DBAPIError


class PostgreSQLErrorCode(StrEnum):
    NOT_NULL_VIOLATION = "23502"
    FOREIGN_KEY_VIOLATION = "23503"
    UNIQUE_VIOLATION = "23505"
    CHECK_VIOLATION = "23514"
    SERIALIZATION_FAILURE = "40001"
    DEADLOCK_DETECTED = "40P01"
    LOCK_NOT_AVAILABLE = "55P03"
    QUERY_CANCELED = "57014"
    ADMIN_SHUTDOWN = "57P01"
    CRASH_SHUTDOWN = "57P02"
    CANNOT_CONNECT_NOW = "57P03"


TRANSIENT_SQLSTATES: Final[frozenset[str]] = frozenset(
    {
        PostgreSQLErrorCode.SERIALIZATION_FAILURE,
        PostgreSQLErrorCode.DEADLOCK_DETECTED,
        PostgreSQLErrorCode.ADMIN_SHUTDOWN,
        PostgreSQLErrorCode.CRASH_SHUTDOWN,
        PostgreSQLErrorCode.CANNOT_CONNECT_NOW,
    }
)


def get_sqlstate(error: BaseException) -> str | None:
    """Return a SQLSTATE from nested SQLAlchemy/driver exceptions.

    SQLAlchemy wraps driver exceptions differently for psycopg and asyncpg.
    This bounded traversal checks the common ``orig``, ``__cause__``, and
    ``__context__`` links without depending on private driver classes.
    """

    pending: list[BaseException] = [error]
    visited: set[int] = set()
    while pending and len(visited) < 16:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(current, attribute, None)
            if isinstance(value, str) and len(value) == 5:
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(current, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


def has_sqlstate(error: BaseException, *codes: str | PostgreSQLErrorCode) -> bool:
    sqlstate = get_sqlstate(error)
    return sqlstate is not None and sqlstate in {str(code) for code in codes}


def is_constraint_violation(error: BaseException) -> bool:
    return has_sqlstate(
        error,
        PostgreSQLErrorCode.NOT_NULL_VIOLATION,
        PostgreSQLErrorCode.FOREIGN_KEY_VIOLATION,
        PostgreSQLErrorCode.UNIQUE_VIOLATION,
        PostgreSQLErrorCode.CHECK_VIOLATION,
    )


def is_unique_violation(error: BaseException) -> bool:
    return has_sqlstate(error, PostgreSQLErrorCode.UNIQUE_VIOLATION)


def is_foreign_key_violation(error: BaseException) -> bool:
    return has_sqlstate(error, PostgreSQLErrorCode.FOREIGN_KEY_VIOLATION)


def is_serialization_failure(error: BaseException) -> bool:
    return has_sqlstate(error, PostgreSQLErrorCode.SERIALIZATION_FAILURE)


def is_deadlock(error: BaseException) -> bool:
    return has_sqlstate(error, PostgreSQLErrorCode.DEADLOCK_DETECTED)


def is_lock_not_available(error: BaseException) -> bool:
    return has_sqlstate(error, PostgreSQLErrorCode.LOCK_NOT_AVAILABLE)


def is_statement_timeout(error: BaseException) -> bool:
    if not has_sqlstate(error, PostgreSQLErrorCode.QUERY_CANCELED):
        return False
    message = str(error).lower()
    return "statement timeout" in message or "canceling statement" in message


def is_retryable_database_error(error: BaseException) -> bool:
    if not isinstance(error, DBAPIError):
        return False
    sqlstate = get_sqlstate(error)
    return sqlstate in TRANSIENT_SQLSTATES


__all__ = [
    "PostgreSQLErrorCode",
    "TRANSIENT_SQLSTATES",
    "get_sqlstate",
    "has_sqlstate",
    "is_constraint_violation",
    "is_deadlock",
    "is_foreign_key_violation",
    "is_lock_not_available",
    "is_retryable_database_error",
    "is_serialization_failure",
    "is_statement_timeout",
    "is_unique_violation",
]
