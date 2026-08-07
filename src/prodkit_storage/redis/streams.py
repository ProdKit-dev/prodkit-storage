"""Small Redis Streams publisher abstraction for outbox dispatchers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import orjson
from redis import Redis
from redis.asyncio import Redis as AsyncRedisClient


class SyncStreamPublisher:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def publish(
        self,
        stream: str,
        event: Mapping[str, Any],
        *,
        maxlen: int | None = None,
    ) -> str:
        _validate_maxlen(maxlen)
        payload = {"data": orjson.dumps(event)}
        message_id = self.client.xadd(stream, payload, maxlen=maxlen, approximate=True)
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)


class AsyncStreamPublisher:
    def __init__(self, client: AsyncRedisClient) -> None:
        self.client = client

    async def publish(
        self,
        stream: str,
        event: Mapping[str, Any],
        *,
        maxlen: int | None = None,
    ) -> str:
        _validate_maxlen(maxlen)
        payload = {"data": orjson.dumps(event)}
        message_id = await self.client.xadd(stream, payload, maxlen=maxlen, approximate=True)
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)


def _validate_maxlen(maxlen: int | None) -> None:
    if maxlen is not None and maxlen <= 0:
        raise ValueError("maxlen must be positive when supplied")
