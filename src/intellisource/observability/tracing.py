"""Tracing middleware for ASGI applications.

Generates a unique trace_id per HTTP request and injects it into
the structlog context for correlated logging.
"""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable, MutableMapping

import structlog

# ASGI type aliases for clarity
ASGIScope = MutableMapping[str, Any]
ASGIReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
ASGISend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class TracingMiddleware:
    """ASGI middleware that injects a unique trace_id into the structlog context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: ASGIScope,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        trace_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            await self.app(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")
