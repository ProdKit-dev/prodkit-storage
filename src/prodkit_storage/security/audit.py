"""Audit payload classification and redaction policies."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    SECRET = "secret"
    REGULATED = "regulated"


class AuditAction(StrEnum):
    KEEP = "keep"
    MASK = "mask"
    DROP = "drop"
    HASH = "hash"
    REJECT = "reject"


class AuditFieldClassifier(Protocol):
    def classify(
        self,
        path: tuple[str, ...],
        value: Any,
    ) -> DataClassification | None: ...


ClassifierHook = Callable[
    [tuple[str, ...], Any], DataClassification | None
]


@dataclass(frozen=True, slots=True)
class NameClassifier:
    """Classify exact dotted paths or matching leaf names."""

    paths: Mapping[str, DataClassification] = field(default_factory=dict)
    leaf_names: Mapping[str, DataClassification] = field(default_factory=dict)

    def classify(
        self,
        path: tuple[str, ...],
        value: Any,
    ) -> DataClassification | None:
        del value
        dotted = ".".join(path).lower()
        if dotted in self.paths:
            return self.paths[dotted]
        if path:
            return self.leaf_names.get(path[-1].lower())
        return None


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    classifiers: Sequence[AuditFieldClassifier | ClassifierHook] = ()
    classification_actions: Mapping[DataClassification, AuditAction] = field(
        default_factory=lambda: {
            DataClassification.PUBLIC: AuditAction.KEEP,
            DataClassification.INTERNAL: AuditAction.KEEP,
            DataClassification.PERSONAL: AuditAction.KEEP,
            DataClassification.SENSITIVE: AuditAction.MASK,
            DataClassification.SECRET: AuditAction.DROP,
            DataClassification.REGULATED: AuditAction.MASK,
        }
    )
    field_actions: Mapping[str, AuditAction] = field(default_factory=dict)
    mask: str = "[REDACTED]"
    hash_secret: bytes | None = None
    max_depth: int = 32

    def sanitize(self, value: Any) -> Any:
        return self._sanitize(value, (), set(), 0)

    def _sanitize(
        self,
        value: Any,
        path: tuple[str, ...],
        visited: set[int],
        depth: int,
    ) -> Any:
        if depth > self.max_depth:
            raise ValueError("audit payload exceeds maximum nesting depth")
        action = self._action(path, value)
        if action is AuditAction.MASK:
            return self.mask
        if action is AuditAction.DROP:
            return _DROP
        if action is AuditAction.REJECT:
            raise ValueError(f"audit field {'.'.join(path)!r} is forbidden")
        if action is AuditAction.HASH:
            return self._hash(value)
        if isinstance(value, Mapping):
            if id(value) in visited:
                raise ValueError("audit payload contains a cycle")
            visited.add(id(value))
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                result = self._sanitize(item, (*path, key_text), visited, depth + 1)
                if result is not _DROP:
                    sanitized[key_text] = result
            visited.remove(id(value))
            return sanitized
        if isinstance(value, (list, tuple)):
            if id(value) in visited:
                raise ValueError("audit payload contains a cycle")
            visited.add(id(value))
            sanitized_items = [
                self._sanitize(item, (*path, str(index)), visited, depth + 1)
                for index, item in enumerate(value)
            ]
            visited.remove(id(value))
            return [item for item in sanitized_items if item is not _DROP]
        return value

    def _action(self, path: tuple[str, ...], value: Any) -> AuditAction:
        dotted = ".".join(path).lower()
        field_action = self.field_actions.get(dotted)
        if field_action is not None:
            return field_action
        for classifier in self.classifiers:
            classification = (
                classifier(path, value)
                if callable(classifier)
                else classifier.classify(path, value)
            )
            if classification is not None:
                return self.classification_actions.get(classification, AuditAction.KEEP)
        return AuditAction.KEEP

    def _hash(self, value: Any) -> str:
        if self.hash_secret is None:
            raise ValueError("hash_secret is required for hashed audit fields")
        digest = hmac.new(
            self.hash_secret,
            repr(value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256:{digest}"


_DROP = object()

_DEFAULT_SECRET_NAMES = {
    "password": DataClassification.SECRET,
    "password_hash": DataClassification.SECRET,
    "access_token": DataClassification.SECRET,
    "refresh_token": DataClassification.SECRET,
    "api_key": DataClassification.SECRET,
    "secret": DataClassification.SECRET,
    "client_secret": DataClassification.SECRET,
    "private_key": DataClassification.SECRET,
    "authorization": DataClassification.SECRET,
    "cookie": DataClassification.SECRET,
    "cvv": DataClassification.SECRET,
    "cvc": DataClassification.SECRET,
    "card_number": DataClassification.REGULATED,
    "pan": DataClassification.REGULATED,
    "ssn": DataClassification.REGULATED,
}

DEFAULT_AUDIT_POLICY = AuditPolicy(
    classifiers=(NameClassifier(leaf_names=_DEFAULT_SECRET_NAMES),)
)


__all__ = [
    "AuditAction",
    "AuditFieldClassifier",
    "AuditPolicy",
    "ClassifierHook",
    "DEFAULT_AUDIT_POLICY",
    "DataClassification",
    "NameClassifier",
]
