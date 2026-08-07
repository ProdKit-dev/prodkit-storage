"""Environment-driven configuration for PostgreSQL, Redis, and telemetry."""

from __future__ import annotations

import hashlib
import re
from functools import cached_property
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from prodkit_storage.exceptions import ConfigurationError

IsolationLevel = Literal[
    "AUTOCOMMIT",
    "READ COMMITTED",
    "REPEATABLE READ",
    "SERIALIZABLE",
]
ProcessType = Literal["app", "worker", "scheduler", "script", "migration", "test"]
DeploymentEnvironment = Literal["development", "test", "staging", "production"]
_INSECURE_CURSOR_SECRET = "replace-this-development-only-secret"
_POSTGRES_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_CUSTOM_SETTING = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_MODEL_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class StorageSettings(BaseSettings):
    """Complete runtime settings.

    A plain ``postgresql://`` URL is accepted and converted to psycopg for sync
    access and asyncpg for async access. Explicit sync/async URLs take priority.
    """

    model_config = SettingsConfigDict(
        env_prefix="PRODKIT_STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    environment: DeploymentEnvironment = "development"
    database_url: SecretStr = Field(
        default=SecretStr("postgresql://prodkit:prodkit@localhost:5432/prodkit")
    )
    sync_database_url: SecretStr | None = None
    async_database_url: SecretStr | None = None
    read_database_url: SecretStr | None = None
    async_read_database_url: SecretStr | None = None

    application_name: str = Field(default="prodkit-storage", max_length=63)
    service_name: str = Field(default="prodkit-storage", max_length=63)
    process_type: ProcessType = "app"
    instance_id: str | None = Field(default=None, max_length=128)

    database_schema: str = "public"
    migration_owner_role: str | None = None
    alembic_model_modules: str = ""
    echo_sql: bool = False
    pool_pre_ping: bool = True
    pool_size: int = Field(default=10, ge=1, le=500)
    max_overflow: int = Field(default=20, ge=0, le=1000)
    pool_timeout_seconds: float = Field(default=30.0, gt=0)
    pool_recycle_seconds: int = Field(default=1800, ge=0)
    connect_timeout_seconds: int = Field(default=10, ge=1)
    command_timeout_seconds: float = Field(default=30.0, gt=0)
    statement_timeout_ms: int = Field(default=30_000, ge=0)
    lock_timeout_ms: int = Field(default=5_000, ge=0)
    idle_in_transaction_timeout_ms: int = Field(default=60_000, ge=0)
    isolation_level: IsolationLevel = "READ COMMITTED"

    tenant_rls_enabled: bool = False
    tenant_required: bool = False
    rls_tenant_setting: str = "app.tenant_id"
    rls_actor_setting: str = "app.actor_id"
    rls_request_setting: str = "app.request_id"

    redis_url: SecretStr = Field(default=SecretStr("redis://localhost:6379/0"))
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0)
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0)
    redis_max_connections: int = Field(default=100, ge=1)
    redis_retry_attempts: int = Field(default=3, ge=0, le=20)
    redis_decode_responses: bool = False
    cache_namespace: str = "prodkit"
    cache_default_ttl_seconds: int = Field(default=300, ge=1)
    cache_ttl_jitter_ratio: float = Field(default=0.10, ge=0, le=0.50)

    cursor_signing_secret: SecretStr = Field(default=SecretStr(_INSECURE_CURSOR_SECRET))
    slow_query_threshold_ms: float = Field(default=250.0, gt=0)
    log_query_parameters: bool = False

    observability_enabled: bool = False
    telemetry_namespace: str = "prodkit.storage"
    otel_service_name: str | None = None
    otel_sqlalchemy_instrumentation: bool = True
    otel_redis_instrumentation: bool = True
    otel_sqlcommenter: bool = False
    otel_include_query_text: bool = False

    @field_validator(
        "application_name",
        "service_name",
        "cache_namespace",
        "telemetry_namespace",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("instance_id")
    @classmethod
    def _normalize_instance_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("migration_owner_role")
    @classmethod
    def _safe_optional_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if _POSTGRES_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("migration_owner_role must be a lowercase PostgreSQL identifier")
        return value

    @field_validator("rls_tenant_setting", "rls_actor_setting", "rls_request_setting")
    @classmethod
    def _safe_setting_name(cls, value: str) -> str:
        value = value.strip()
        if _CUSTOM_SETTING.fullmatch(value) is None:
            raise ValueError("RLS setting names must be valid PostgreSQL custom settings")
        return value

    @field_validator("cursor_signing_secret")
    @classmethod
    def _strong_cursor_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("cursor_signing_secret must contain at least 32 bytes")
        return value

    @field_validator("redis_url")
    @classmethod
    def _valid_redis_url(cls, value: SecretStr) -> SecretStr:
        scheme = urlsplit(value.get_secret_value()).scheme
        if scheme not in {"redis", "rediss", "unix"}:
            raise ValueError("redis_url must use redis://, rediss://, or unix://")
        return value

    @field_validator("alembic_model_modules")
    @classmethod
    def _safe_model_modules(cls, value: str) -> str:
        modules = [item.strip() for item in value.split(",") if item.strip()]
        if any(_MODEL_MODULE.fullmatch(module) is None for module in modules):
            raise ValueError("alembic_model_modules must contain comma-separated module names")
        return ",".join(dict.fromkeys(modules))

    @field_validator("database_schema")
    @classmethod
    def _safe_schema(cls, value: str) -> str:
        value = value.strip()
        if _POSTGRES_IDENTIFIER.fullmatch(value) is None:
            raise ValueError("database_schema must be a lowercase PostgreSQL identifier")
        return value

    @model_validator(mode="after")
    def _validate_urls_and_environment(self) -> StorageSettings:
        for url in (
            self.database_url,
            self.sync_database_url,
            self.async_database_url,
            self.read_database_url,
            self.async_read_database_url,
        ):
            if url is None:
                continue
            parsed = make_url(url.get_secret_value())
            if parsed.get_backend_name() != "postgresql":
                raise ValueError("all database URLs must use PostgreSQL")

        if self.environment in {"staging", "production"}:
            if self.cursor_signing_secret.get_secret_value() == _INSECURE_CURSOR_SECRET:
                raise ValueError(
                    "cursor_signing_secret must be explicitly configured in staging/production"
                )
        return self

    @cached_property
    def sync_url(self) -> URL:
        raw = (self.sync_database_url or self.database_url).get_secret_value()
        return _with_driver(make_url(raw), "postgresql+psycopg")

    @cached_property
    def async_url(self) -> URL:
        raw = (self.async_database_url or self.database_url).get_secret_value()
        return _with_driver(make_url(raw), "postgresql+asyncpg")

    @cached_property
    def sync_read_url(self) -> URL | None:
        if self.read_database_url is None:
            return None
        return _with_driver(
            make_url(self.read_database_url.get_secret_value()),
            "postgresql+psycopg",
        )

    @cached_property
    def async_read_url(self) -> URL | None:
        candidate = self.async_read_database_url or self.read_database_url
        if candidate is None:
            return None
        return _with_driver(make_url(candidate.get_secret_value()), "postgresql+asyncpg")

    @property
    def alembic_model_module_names(self) -> tuple[str, ...]:
        return tuple(item for item in self.alembic_model_modules.split(",") if item)

    @property
    def redis_dsn(self) -> str:
        return self.redis_url.get_secret_value()

    @property
    def cursor_secret_bytes(self) -> bytes:
        secret = self.cursor_signing_secret.get_secret_value().encode("utf-8")
        if len(secret) < 32:
            raise ConfigurationError("cursor_signing_secret must contain at least 32 bytes")
        return secret

    def client_name(self, component: str, *, max_length: int = 63) -> str:
        """Build a stable process/component identity for PostgreSQL and Redis."""

        component = component.strip().replace("_", "-")
        if not component:
            raise ValueError("component must not be empty")
        parts = [self.application_name, self.process_type, component]
        if self.instance_id:
            parts.append(self.instance_id)
        raw = "-".join(parts)
        if len(raw) <= max_length:
            return raw
        digest = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return f"{raw[: max_length - len(digest) - 1]}-{digest}"


def _with_driver(url: URL, drivername: str) -> URL:
    return url.set(drivername=drivername)


__all__ = [
    "DeploymentEnvironment",
    "IsolationLevel",
    "ProcessType",
    "StorageSettings",
]
