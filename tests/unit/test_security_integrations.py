from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from prodkit_storage.database.sorting import SortField, SortRegistry
from prodkit_storage.integrations.fastapi.sorting import create_sorting_dependency
from prodkit_storage.integrations.pydantic import (
    EmptyStringToNone,
    NoNulString,
    PostgresInt32,
    StorageSchema,
    TrimmedString,
)
from prodkit_storage.models import OutboxEvent
from prodkit_storage.security.audit import (
    AuditAction,
    AuditPolicy,
    DEFAULT_AUDIT_POLICY,
    DataClassification,
    NameClassifier,
)
from prodkit_storage.security.roles import PostgresRoleNames, render_role_bootstrap_sql
from prodkit_storage.security.secrets import (
    MappingSecretProvider,
    SecretBinding,
    load_storage_settings,
)


class SafePayload(StorageSchema):
    name: NoNulString
    title: TrimmedString
    optional: EmptyStringToNone
    count: PostgresInt32
    nested: dict[str, Any] = {}


def test_audit_policy_redacts_nested_sensitive_data() -> None:
    payload = {
        "name": "Ada",
        "password": "secret",
        "profile": {"access_token": "token", "email": "ada@example.test"},
    }
    sanitized = DEFAULT_AUDIT_POLICY.sanitize(payload)
    assert sanitized == {
        "name": "Ada",
        "profile": {"email": "ada@example.test"},
    }

    policy = AuditPolicy(
        classifiers=(
            NameClassifier(leaf_names={"email": DataClassification.SENSITIVE}),
        ),
        field_actions={"profile.internal": AuditAction.REJECT},
    )
    assert policy.sanitize({"email": "a@b.test"}) == {"email": "[REDACTED]"}
    with pytest.raises(ValueError, match="forbidden"):
        policy.sanitize({"profile": {"internal": "nope"}})


def test_secret_provider_and_role_template() -> None:
    settings = load_storage_settings(
        MappingSecretProvider(
            {
                "DATABASE_URL": "postgresql://u:p@db/app",
                "CURSOR_SECRET": "x" * 32,
            }
        ),
        (
            SecretBinding("database_url", "DATABASE_URL"),
            SecretBinding("cursor_signing_secret", "CURSOR_SECRET"),
        ),
    )
    assert settings.sync_url.drivername == "postgresql+psycopg"

    sql = render_role_bootstrap_sql(database="prodkit", roles=PostgresRoleNames())
    assert "NOBYPASSRLS" in sql
    assert "prodkit_runtime" in sql
    assert "ALTER DATABASE prodkit OWNER TO prodkit_owner" in sql
    with pytest.raises(ValueError, match="identifier"):
        render_role_bootstrap_sql(database="bad-name")


def test_database_safe_pydantic_types() -> None:
    payload = SafePayload(
        name="Ada",
        title="  Engineer  ",
        optional="   ",
        count=10,
        nested={"value": "safe"},
    )
    assert payload.title == "Engineer"
    assert payload.optional is None
    with pytest.raises(ValidationError, match="NUL"):
        SafePayload(name="bad\x00value", title="x", count=1)
    with pytest.raises(ValidationError):
        SafePayload(name="ok", title="x", count=2**31)


@pytest.mark.asyncio
async def test_fastapi_sorting_dependency_uses_registry() -> None:
    registry = SortRegistry(
        fields={
            "created_at": SortField("created_at", OutboxEvent.created_at),
            "id": SortField("id", OutboxEvent.id),
        },
        default=("-created_at",),
        tie_breaker="id",
    )
    dependency = create_sorting_dependency(registry)
    plan = await dependency(["created_at"])
    assert plan.terms[0].field.name == "created_at"


class AsyncMappingSecretProvider:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    async def get_secret(self, name: str) -> str | None:
        return self.values.get(name)


@pytest.mark.asyncio
async def test_async_secret_provider_and_binding_validation() -> None:
    from prodkit_storage.security.secrets import (
        EnvironmentSecretProvider,
        load_storage_settings_async,
    )

    settings = await load_storage_settings_async(
        AsyncMappingSecretProvider(
            {
                "DATABASE_URL": "postgresql://u:p@db/app",
                "CURSOR_SECRET": "z" * 32,
            }
        ),
        (
            SecretBinding("database_url", "DATABASE_URL"),
            SecretBinding("cursor_signing_secret", "CURSOR_SECRET"),
        ),
    )
    assert settings.async_url.drivername == "postgresql+asyncpg"
    assert EnvironmentSecretProvider({}).get_secret("PATH") is None

    with pytest.raises(ValueError, match="unknown storage setting"):
        load_storage_settings(
            MappingSecretProvider({"X": "value"}),
            (SecretBinding("database_urll", "X"),),
        )
    with pytest.raises(ValueError, match="duplicate"):
        load_storage_settings(
            MappingSecretProvider({"A": "x", "B": "y"}),
            (
                SecretBinding("database_url", "A"),
                SecretBinding("database_url", "B"),
            ),
        )
