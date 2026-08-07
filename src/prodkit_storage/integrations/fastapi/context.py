"""ASGI request-context propagation with an application-owned resolver."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from prodkit_storage.context import RequestContext, request_context

ContextResolver = Callable[[HTTPConnection], RequestContext | Awaitable[RequestContext]]


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, resolver: ContextResolver) -> None:
        self.app = app
        self.resolver = resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        resolved = self.resolver(connection)
        context = await resolved if inspect.isawaitable(resolved) else resolved
        with request_context(context):
            await self.app(scope, receive, send)


__all__ = ["ContextResolver", "RequestContextMiddleware"]
