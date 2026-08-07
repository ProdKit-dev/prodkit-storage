"""Redis-backed idempotency state machine."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Literal

import orjson
from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient

from prodkit_storage.exceptions import IdempotencyConflictError

Status = Literal["started", "in_progress", "completed"]

_BEGIN_SCRIPT = """
local existing = redis.call('get', KEYS[1])
if existing then return existing end
redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
return ARGV[1]
"""

_COMPLETE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if not current then return 0 end
local decoded = cjson.decode(current)
if decoded['token'] ~= ARGV[1] then return -1 end
if decoded['fingerprint'] ~= ARGV[2] then return -1 end
redis.call('set', KEYS[1], ARGV[3], 'EX', ARGV[4])
return 1
"""

_RELEASE_SCRIPT = """
local current = redis.call('get', KEYS[1])
if not current then return 0 end
local decoded = cjson.decode(current)
if decoded['token'] ~= ARGV[1] then return -1 end
return redis.call('del', KEYS[1])
"""


@dataclass(frozen=True, slots=True)
class IdempotencyResult:
    status: Status
    token: str | None = None
    response: Any = None


def request_fingerprint(value: Any) -> str:
    payload = orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()


class SyncIdempotencyStore:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def begin(
        self,
        key: str,
        fingerprint: str,
        *,
        processing_ttl_seconds: int = 60,
    ) -> IdempotencyResult:
        if processing_ttl_seconds <= 0 or not fingerprint:
            raise ValueError("processing TTL and fingerprint must be valid")
        token = secrets.token_urlsafe(24)
        record = {"status": "in_progress", "token": token, "fingerprint": fingerprint}
        raw = self.client.eval(
            _BEGIN_SCRIPT, 1, key, orjson.dumps(record), processing_ttl_seconds
        )
        existing = orjson.loads(raw)
        if existing.get("token") == token:
            return IdempotencyResult(status="started", token=token)
        if existing.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError("idempotency key was reused with a different request")
        if existing["status"] == "completed":
            return IdempotencyResult(status="completed", response=existing.get("response"))
        return IdempotencyResult(status="in_progress")

    def complete(
        self,
        key: str,
        token: str,
        fingerprint: str,
        response: Any,
        *,
        ttl_seconds: int = 86_400,
    ) -> None:
        if ttl_seconds <= 0 or not fingerprint:
            raise ValueError("completion TTL and fingerprint must be valid")
        record = orjson.dumps(
            {"status": "completed", "fingerprint": fingerprint, "response": response}
        )
        result = int(
            self.client.eval(
                _COMPLETE_SCRIPT, 1, key, token, fingerprint, record, ttl_seconds
            )
        )
        if result != 1:
            raise IdempotencyConflictError("idempotency lease is missing or no longer owned")

    def release(self, key: str, token: str) -> bool:
        return int(self.client.eval(_RELEASE_SCRIPT, 1, key, token)) == 1


class AsyncIdempotencyStore:
    def __init__(self, client: AsyncRedisClient) -> None:
        self.client = client

    async def begin(
        self,
        key: str,
        fingerprint: str,
        *,
        processing_ttl_seconds: int = 60,
    ) -> IdempotencyResult:
        if processing_ttl_seconds <= 0 or not fingerprint:
            raise ValueError("processing TTL and fingerprint must be valid")
        token = secrets.token_urlsafe(24)
        record = {"status": "in_progress", "token": token, "fingerprint": fingerprint}
        raw = await self.client.eval(
            _BEGIN_SCRIPT, 1, key, orjson.dumps(record), processing_ttl_seconds
        )
        existing = orjson.loads(raw)
        if existing.get("token") == token:
            return IdempotencyResult(status="started", token=token)
        if existing.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError("idempotency key was reused with a different request")
        if existing["status"] == "completed":
            return IdempotencyResult(status="completed", response=existing.get("response"))
        return IdempotencyResult(status="in_progress")

    async def complete(
        self,
        key: str,
        token: str,
        fingerprint: str,
        response: Any,
        *,
        ttl_seconds: int = 86_400,
    ) -> None:
        if ttl_seconds <= 0 or not fingerprint:
            raise ValueError("completion TTL and fingerprint must be valid")
        record = orjson.dumps(
            {"status": "completed", "fingerprint": fingerprint, "response": response}
        )
        result = int(
            await self.client.eval(
                _COMPLETE_SCRIPT, 1, key, token, fingerprint, record, ttl_seconds
            )
        )
        if result != 1:
            raise IdempotencyConflictError("idempotency lease is missing or no longer owned")

    async def release(self, key: str, token: str) -> bool:
        return int(await self.client.eval(_RELEASE_SCRIPT, 1, key, token)) == 1
