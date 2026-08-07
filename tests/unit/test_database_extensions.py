from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.errors import (
    PostgreSQLErrorCode,
    get_sqlstate,
    is_deadlock,
    is_lock_not_available,
    is_retryable_database_error,
    is_statement_timeout,
    is_unique_violation,
)
from prodkit_storage.database.types import IntegerEnumType, StringEnumType


class StateError(Exception):
    def __init__(self, sqlstate: str, message: str = "database error") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class Status(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


def wrapped(sqlstate: str, message: str = "database error") -> DBAPIError:
    return DBAPIError("statement", {}, StateError(sqlstate, message), False)


def test_postgres_error_classification_traverses_wrappers() -> None:
    assert get_sqlstate(wrapped("23505")) == "23505"
    assert is_unique_violation(wrapped(PostgreSQLErrorCode.UNIQUE_VIOLATION))
    assert is_deadlock(wrapped(PostgreSQLErrorCode.DEADLOCK_DETECTED))
    assert is_retryable_database_error(wrapped(PostgreSQLErrorCode.DEADLOCK_DETECTED))
    assert is_lock_not_available(wrapped(PostgreSQLErrorCode.LOCK_NOT_AVAILABLE))
    assert is_statement_timeout(
        wrapped(PostgreSQLErrorCode.QUERY_CANCELED, "canceling statement due to statement timeout")
    )


def test_portable_enum_types_validate_and_round_trip() -> None:
    string_type = StringEnumType(Status)
    integer_type = IntegerEnumType(Priority)
    dialect: Any = None
    assert string_type.process_bind_param(Status.ACTIVE, dialect) == "active"
    assert string_type.process_result_value("disabled", dialect) is Status.DISABLED
    assert integer_type.process_bind_param(Priority.HIGH, dialect) == 2
    assert integer_type.process_result_value(1, dialect) is Priority.LOW
    with pytest.raises(ValueError, match="smaller"):
        StringEnumType(Status, length=3)


def test_process_client_identity_is_stable_and_bounded() -> None:
    settings = StorageSettings(
        application_name="prodkit",
        process_type="worker",
        instance_id="worker-01",
    )
    assert settings.client_name("async-write") == "prodkit-worker-async-write-worker-01"
    bounded = StorageSettings(application_name="x" * 63, instance_id="y" * 100).client_name(
        "async-write"
    )
    assert len(bounded) <= 63
