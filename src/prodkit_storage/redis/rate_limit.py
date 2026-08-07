"""Atomic Redis token-bucket rate limiter using server time."""

from __future__ import annotations

from dataclasses import dataclass

from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient

_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local state = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(state[1]) or capacity
local updated_at = tonumber(state[2]) or now_ms
local elapsed = math.max(0, now_ms - updated_at)
tokens = math.min(capacity, tokens + elapsed * refill_per_ms)
local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_after_ms = math.ceil((requested - tokens) / refill_per_ms)
end
redis.call('HSET', key, 'tokens', tokens, 'updated_at', now_ms)
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, math.floor(tokens), retry_after_ms}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_ms: int


class SyncRateLimiter:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def check(
        self,
        key: str,
        *,
        capacity: int,
        refill_rate_per_second: float,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate(capacity, refill_rate_per_second, cost)
        ttl_ms = max(1000, int(capacity / refill_rate_per_second * 2000))
        result = self.client.eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            key,
            capacity,
            refill_rate_per_second / 1000,
            cost,
            ttl_ms,
        )
        return RateLimitDecision(bool(result[0]), int(result[1]), int(result[2]))


class AsyncRateLimiter:
    def __init__(self, client: AsyncRedisClient) -> None:
        self.client = client

    async def check(
        self,
        key: str,
        *,
        capacity: int,
        refill_rate_per_second: float,
        cost: int = 1,
    ) -> RateLimitDecision:
        _validate(capacity, refill_rate_per_second, cost)
        ttl_ms = max(1000, int(capacity / refill_rate_per_second * 2000))
        result = await self.client.eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            key,
            capacity,
            refill_rate_per_second / 1000,
            cost,
            ttl_ms,
        )
        return RateLimitDecision(bool(result[0]), int(result[1]), int(result[2]))


def _validate(capacity: int, rate: float, cost: int) -> None:
    if capacity <= 0 or rate <= 0 or cost <= 0:
        raise ValueError("capacity, refill rate, and cost must be positive")
    if cost > capacity:
        raise ValueError("cost cannot exceed bucket capacity")
