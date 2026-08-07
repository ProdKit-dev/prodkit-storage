"""Collision-resistant Redis key construction."""

from __future__ import annotations

import hashlib
from urllib.parse import quote


class KeyBuilder:
    def __init__(self, namespace: str, *, version: int = 1, max_length: int = 240) -> None:
        if version < 1:
            raise ValueError("Redis key version must be positive")
        if max_length < 80:
            raise ValueError("Redis max key length must be at least 80 bytes")
        self.namespace = _segment(namespace)
        self.version = version
        self.max_length = max_length

    def build(self, *parts: object) -> str:
        segments = [self.namespace, f"v{self.version}", *(_segment(str(part)) for part in parts)]
        key = ":".join(segments)
        if len(key.encode("utf-8")) <= self.max_length:
            return key
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        suffix = f":sha256:{digest}"
        prefix_budget = self.max_length - len(suffix)
        prefix = ":".join(segments[:2])[:prefix_budget]
        return f"{prefix}{suffix}"

    def tag(self, tag: str) -> str:
        return self.build("tag", tag)


def _segment(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Redis key segments must not be empty")
    return quote(value, safe="-_.~")
