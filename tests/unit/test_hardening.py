from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from prodkit_storage.config import StorageSettings
from prodkit_storage.database.types import IntegerEnumType, StringEnumType
from prodkit_storage.exceptions import OutboxLeaseLostError
from prodkit_storage.outbox import complete_outbox_event
from prodkit_storage.security.roles import (
    render_post_migration_grants_sql,
    render_role_bootstrap_sql,
)


class Status(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class CompleteSession:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statement: Any = None

    def execute(self, statement: Any) -> Result:
        self.statement = statement
        return Result(self.rowcount)


def test_production_rejects_known_cursor_secret() -> None:
    with pytest.raises(ValidationError, match="cursor_signing_secret"):
        StorageSettings(environment="production")

    settings = StorageSettings(
        environment="production",
        cursor_signing_secret="a-production-secret-that-is-longer-than-32-bytes",
    )
    assert settings.environment == "production"


def test_migration_owner_role_is_identifier_validated() -> None:
    assert StorageSettings(migration_owner_role="prodkit_owner").migration_owner_role == (
        "prodkit_owner"
    )
    with pytest.raises(ValidationError, match="migration_owner_role"):
        StorageSettings(migration_owner_role="owner; DROP SCHEMA public")


def test_role_templates_require_explicit_set_role_and_append_only_audit() -> None:
    bootstrap = render_role_bootstrap_sql(database="prodkit")
    assert "GRANT prodkit_owner TO prodkit_migrator" in bootstrap
    assert "GRANT USAGE, CREATE ON SCHEMA" not in bootstrap
    assert "Alembic must SET ROLE" in bootstrap

    grants = render_post_migration_grants_sql()
    assert "REVOKE SELECT, UPDATE, DELETE" in grants
    assert "storage_audit_events" in grants
    assert "REVOKE DELETE" in grants
    assert "storage_outbox_events" in grants


def test_portable_enum_types_reject_unknown_raw_values() -> None:
    string_type = StringEnumType(Status)
    integer_type = IntegerEnumType(Priority)

    assert string_type.process_bind_param("active", None) == "active"  # type: ignore[arg-type]
    assert integer_type.process_bind_param(2, None) == 2  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not a valid value"):
        string_type.process_bind_param("unknown", None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not a valid value"):
        integer_type.process_bind_param(99, None)  # type: ignore[arg-type]


def test_outbox_completion_rejects_lost_lease() -> None:
    event_id = UUID("00000000-0000-0000-0000-000000000001")
    lock_token = UUID("00000000-0000-0000-0000-000000000002")

    complete_outbox_event(
        CompleteSession(1),  # type: ignore[arg-type]
        event_id=event_id,
        lock_token=lock_token,
    )

    with pytest.raises(OutboxLeaseLostError):
        complete_outbox_event(
            CompleteSession(0),  # type: ignore[arg-type]
            event_id=event_id,
            lock_token=lock_token,
        )
