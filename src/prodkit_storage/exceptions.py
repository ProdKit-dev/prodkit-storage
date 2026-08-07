"""Storage-specific exception hierarchy."""

from __future__ import annotations

from typing import Any


class StorageError(Exception):
    """Base exception for the package."""


class ConfigurationError(StorageError):
    """Raised when storage configuration is invalid."""


class NotFoundError(StorageError):
    """Raised when a requested persistent entity does not exist."""

    def __init__(self, model_name: str, identity: Any) -> None:
        super().__init__(f"{model_name} with identity {identity!r} was not found")
        self.model_name = model_name
        self.identity = identity


class ConflictError(StorageError):
    """Raised when a uniqueness or concurrency conflict occurs."""


class TenantContextError(StorageError):
    """Raised when tenant-scoped work is attempted without a tenant context."""


class LockNotAcquiredError(StorageError):
    """Raised when a requested distributed or advisory lock cannot be acquired."""


class IdempotencyConflictError(StorageError):
    """Raised when an idempotency key is reused with incompatible request data."""
