"""Per-loop aioredis client cache (B-037).

``LazyLoopRedis`` wraps ``aioredis.from_url`` construction so that each
running asyncio event loop receives its own underlying ``aioredis.Redis``
instance. This is required for Celery prefork workers that drive async
coroutines via ``asyncio.run()``: every ``asyncio.run`` call opens a new
event loop, runs the coroutine, then closes the loop — leaving any
aioredis connection pool that touched that loop bound to a dead loop.
Subsequent ``asyncio.run()`` invocations that reuse the same client crash
with ``RuntimeError: Event loop is closed``.

The wrapper is transparent to all aioredis consumers
(``IdempotencyGuard`` / ``CircuitBreaker`` / ``RateLimiter`` / ``Distributors``):
it forwards every attribute access to the per-loop underlying client via
``__getattr__``, so ``await wrapper.set(...)`` / ``await wrapper.hgetall(...)``
/ ``async for k in wrapper.scan_iter(...)`` all behave identically to
the wrapped client.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import redis.asyncio as aioredis

__all__ = ["LazyLoopRedis"]


class LazyLoopRedis:
    """aioredis client wrapper keyed by running event loop id."""

    def __init__(
        self,
        url: str,
        *,
        factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._url = url
        self._factory = factory or aioredis.from_url
        self._clients: dict[int, Any] = {}

    def _get_client(self) -> Any:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        client = self._clients.get(loop_id)
        if client is not None:
            return client
        client = self._factory(self._url)
        self._clients[loop_id] = client
        return client

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _delegate(*args: Any, **kwargs: Any) -> Any:
            return getattr(self._get_client(), name)(*args, **kwargs)

        return _delegate
