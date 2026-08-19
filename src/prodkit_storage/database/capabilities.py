"""PostgreSQL capability discovery without privileged mutation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

DEFAULT_EXTENSION_NAMES = ("pgcrypto", "postgis", "vector")


class DatabaseCapabilityError(RuntimeError):
    """Raised when a required PostgreSQL capability is unavailable."""


@dataclass(frozen=True, slots=True)
class ExtensionCapability:
    """Availability and installation state for one PostgreSQL extension."""

    name: str
    default_version: str | None
    installed_version: str | None

    @property
    def available(self) -> bool:
        return self.default_version is not None

    @property
    def installed(self) -> bool:
        return self.installed_version is not None


@dataclass(frozen=True, slots=True)
class PostgreSQLCapabilities:
    """Stable snapshot of reusable PostgreSQL runtime capabilities."""

    server_version: str
    server_version_num: int
    extensions: tuple[ExtensionCapability, ...]
    access_methods: tuple[str, ...]
    text_search_configs: tuple[str, ...]

    def extension(self, name: str) -> ExtensionCapability:
        normalized = _normalize_name(name, "extension")
        for extension in self.extensions:
            if extension.name == normalized:
                return extension
        return ExtensionCapability(normalized, None, None)

    def has_extension(self, name: str) -> bool:
        return self.extension(name).installed

    def has_access_method(self, name: str) -> bool:
        return _normalize_name(name, "access method") in self.access_methods

    def has_text_search_config(self, name: str) -> bool:
        return _normalize_name(name, "text search config") in self.text_search_configs

    @property
    def pgvector_version(self) -> str | None:
        return self.extension("vector").installed_version

    @property
    def supports_pgvector(self) -> bool:
        return self.has_extension("vector")

    @property
    def supports_hnsw(self) -> bool:
        return self.supports_pgvector and self.has_access_method("hnsw")

    @property
    def supports_ivfflat(self) -> bool:
        return self.supports_pgvector and self.has_access_method("ivfflat")

    @property
    def supports_full_text_search(self) -> bool:
        return self.has_access_method("gin") and bool(self.text_search_configs)


def inspect_postgresql_capabilities_sync(
    connection: Connection,
    *,
    extension_names: Iterable[str] = DEFAULT_EXTENSION_NAMES,
) -> PostgreSQLCapabilities:
    """Inspect PostgreSQL capabilities through an existing sync connection.

    This function is read-only. It never creates or upgrades extensions.
    """

    names = _normalize_names(extension_names, "extension")
    server_version = str(connection.scalar(text("SHOW server_version")))
    server_version_num = int(str(connection.scalar(text("SHOW server_version_num"))))
    extension_rows = connection.execute(
        text(
            "SELECT name, default_version, installed_version "
            "FROM pg_available_extensions ORDER BY name"
        )
    ).mappings()
    access_methods = tuple(
        str(value)
        for value in connection.scalars(text("SELECT amname FROM pg_am ORDER BY amname"))
    )
    text_search_configs = tuple(
        str(value)
        for value in connection.scalars(text("SELECT cfgname FROM pg_ts_config ORDER BY cfgname"))
    )
    return PostgreSQLCapabilities(
        server_version=server_version,
        server_version_num=server_version_num,
        extensions=_extension_snapshot(extension_rows, names),
        access_methods=access_methods,
        text_search_configs=text_search_configs,
    )


async def inspect_postgresql_capabilities_async(
    connection: AsyncConnection,
    *,
    extension_names: Iterable[str] = DEFAULT_EXTENSION_NAMES,
) -> PostgreSQLCapabilities:
    """Inspect PostgreSQL capabilities through an existing async connection."""

    names = _normalize_names(extension_names, "extension")
    server_version = str(await connection.scalar(text("SHOW server_version")))
    server_version_num = int(str(await connection.scalar(text("SHOW server_version_num"))))
    extension_result = await connection.execute(
        text(
            "SELECT name, default_version, installed_version "
            "FROM pg_available_extensions ORDER BY name"
        )
    )
    access_result = await connection.execute(text("SELECT amname FROM pg_am ORDER BY amname"))
    config_result = await connection.execute(
        text("SELECT cfgname FROM pg_ts_config ORDER BY cfgname")
    )
    return PostgreSQLCapabilities(
        server_version=server_version,
        server_version_num=server_version_num,
        extensions=_extension_snapshot(extension_result.mappings(), names),
        access_methods=tuple(str(row[0]) for row in access_result),
        text_search_configs=tuple(str(row[0]) for row in config_result),
    )


def require_postgresql_capabilities(
    capabilities: PostgreSQLCapabilities,
    *,
    extensions: Iterable[str] = (),
    access_methods: Iterable[str] = (),
    text_search_configs: Iterable[str] = (),
) -> None:
    """Fail closed when explicitly required capabilities are unavailable."""

    required_extensions = _normalize_names(extensions, "extension")
    required_access_methods = _normalize_names(access_methods, "access method")
    required_configs = _normalize_names(text_search_configs, "text search config")

    missing_extensions = tuple(
        name for name in required_extensions if not capabilities.has_extension(name)
    )
    missing_access_methods = tuple(
        name for name in required_access_methods if not capabilities.has_access_method(name)
    )
    missing_configs = tuple(
        name for name in required_configs if not capabilities.has_text_search_config(name)
    )
    if not (missing_extensions or missing_access_methods or missing_configs):
        return

    parts: list[str] = []
    if missing_extensions:
        parts.append(f"extensions={','.join(missing_extensions)}")
    if missing_access_methods:
        parts.append(f"access_methods={','.join(missing_access_methods)}")
    if missing_configs:
        parts.append(f"text_search_configs={','.join(missing_configs)}")
    raise DatabaseCapabilityError("missing PostgreSQL capabilities: " + "; ".join(parts))


def _extension_snapshot(
    rows: Iterable[RowMapping],
    names: tuple[str, ...],
) -> tuple[ExtensionCapability, ...]:
    selected = set(names)
    found: dict[str, ExtensionCapability] = {}
    for mapping in rows:
        name = str(mapping["name"])
        if name not in selected:
            continue
        default_version = mapping["default_version"]
        installed_version = mapping["installed_version"]
        found[name] = ExtensionCapability(
            name=name,
            default_version=None if default_version is None else str(default_version),
            installed_version=None if installed_version is None else str(installed_version),
        )
    return tuple(found.get(name, ExtensionCapability(name, None, None)) for name in names)


def _normalize_names(values: Iterable[str], kind: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_normalize_name(value, kind) for value in values))


def _normalize_name(value: str, kind: str) -> str:
    normalized = value.strip().lower()
    invalid_character = any(
        not (character.isalnum() or character == "_") for character in normalized
    )
    if not normalized or invalid_character:
        raise ValueError(f"{kind} name must contain only letters, digits, and underscores")
    return normalized


__all__ = [
    "DEFAULT_EXTENSION_NAMES",
    "DatabaseCapabilityError",
    "ExtensionCapability",
    "PostgreSQLCapabilities",
    "inspect_postgresql_capabilities_async",
    "inspect_postgresql_capabilities_sync",
    "require_postgresql_capabilities",
]
