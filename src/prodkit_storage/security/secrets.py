"""Provider-neutral secret resolution contracts."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from prodkit_storage.config import StorageSettings


class SecretProvider(Protocol):
    def get_secret(self, name: str) -> str | None: ...


class AsyncSecretProvider(Protocol):
    async def get_secret(self, name: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class EnvironmentSecretProvider:
    environ: Mapping[str, str] | None = None

    def get_secret(self, name: str) -> str | None:
        source = self.environ if self.environ is not None else os.environ
        return source.get(name)


@dataclass(frozen=True, slots=True)
class MappingSecretProvider:
    values: Mapping[str, str]

    def get_secret(self, name: str) -> str | None:
        return self.values.get(name)


@dataclass(frozen=True, slots=True)
class SecretBinding:
    setting: str
    secret_name: str
    required: bool = True


def load_storage_settings(
    provider: SecretProvider,
    bindings: tuple[SecretBinding, ...],
    **overrides: object,
) -> StorageSettings:
    values = dict(overrides)
    _validate_bindings(bindings)
    for binding in bindings:
        value = provider.get_secret(binding.secret_name)
        if value is None:
            if binding.required:
                raise ValueError(f"required secret {binding.secret_name!r} was not found")
            continue
        values[binding.setting] = value
    return StorageSettings.model_validate(values)


async def load_storage_settings_async(
    provider: AsyncSecretProvider,
    bindings: tuple[SecretBinding, ...],
    **overrides: object,
) -> StorageSettings:
    values = dict(overrides)
    _validate_bindings(bindings)
    for binding in bindings:
        value = await provider.get_secret(binding.secret_name)
        if value is None:
            if binding.required:
                raise ValueError(
                    f"required secret {binding.secret_name!r} was not found"
                )
            continue
        values[binding.setting] = value
    return StorageSettings.model_validate(values)


def _validate_bindings(bindings: tuple[SecretBinding, ...]) -> None:
    seen: set[str] = set()
    for binding in bindings:
        if binding.setting not in StorageSettings.model_fields:
            raise ValueError(f"unknown storage setting: {binding.setting!r}")
        if binding.setting in seen:
            raise ValueError(f"duplicate secret binding for {binding.setting!r}")
        if not binding.secret_name.strip():
            raise ValueError("secret_name must not be empty")
        seen.add(binding.setting)


__all__ = [
    "AsyncSecretProvider",
    "EnvironmentSecretProvider",
    "MappingSecretProvider",
    "SecretBinding",
    "SecretProvider",
    "load_storage_settings",
    "load_storage_settings_async",
]
