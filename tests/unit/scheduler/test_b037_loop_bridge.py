"""B-037 worker async/sync bridge hardening — RED tests.

Production failure (CORRECTIONS-LOG #12, B-031 阶段 1 步骤 4):

    worker process consumes run_pipeline → CeleryTasks._run_sync(
    asyncio.run(coro)) opens loop A → aioredis client's connection pool
    binds to loop A on first await → asyncio.run() closes loop A →
    next _run_sync(asyncio.run(coro)) opens loop B → tries to reuse
    redis_client.set(...) bound to dead loop A → RuntimeError("Event loop
    is closed").

Same failure mode applies to async SQLAlchemy engines: the engine's
connection pool is loop-bound on first checkout.

Fix design (option A — per-task lazy + NullPool, see B-037 backlog):

1. ``intellisource.scheduler.lazy_redis.LazyLoopRedis`` wraps aioredis
   client construction; caches one ``aioredis.Redis`` per running event
   loop and transparently delegates all attribute access (set/get/delete/
   eval/hgetall/hset/setex/scan_iter/ping/aclose) to the per-loop client.
2. ``scheduler.boot._build_redis_client`` returns a ``LazyLoopRedis``.
3. ``scheduler.boot.init_worker_session_factory`` constructs the async
   engine with ``poolclass=NullPool`` so each session checkout opens a
   fresh DB connection (no cross-loop reuse).

These changes are invisible to downstream Redis consumers
(IdempotencyGuard / CircuitBreaker / RateLimiter / Distributors) — the
wrapper quacks like an aioredis client.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Test double — faithful simulation of aioredis loop-bound pool failure
# ---------------------------------------------------------------------------


class _LoopBoundFakeRedis:
    """Captures the loop of its first awaited call and raises the exact
    ``RuntimeError("Event loop is closed")`` if a later await happens on a
    different (and closed) loop — matching production aioredis behavior.
    """

    def __init__(self) -> None:
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    def _check_loop(self) -> None:
        current = asyncio.get_running_loop()
        if self._bound_loop is None:
            self._bound_loop = current
            return
        if self._bound_loop is current:
            return
        if self._bound_loop.is_closed():
            raise RuntimeError("Event loop is closed")

    async def set(self, *_args: Any, **_kwargs: Any) -> bool:
        self._check_loop()
        return True

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        self._check_loop()
        return None

    async def delete(self, *_args: Any, **_kwargs: Any) -> int:
        self._check_loop()
        return 1

    async def ping(self) -> bool:
        self._check_loop()
        return True

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# LazyLoopRedis contract
# ---------------------------------------------------------------------------


class TestLazyLoopRedisImport:
    def test_module_exists(self) -> None:
        """B-037 GREEN: scheduler.lazy_redis must exist."""
        import intellisource.scheduler.lazy_redis as mod

        assert hasattr(mod, "LazyLoopRedis"), (
            "B-037: scheduler.lazy_redis must export LazyLoopRedis"
        )


class TestLazyLoopRedisPerLoopBinding:
    def test_fresh_client_per_event_loop(self) -> None:
        """B-037 GREEN: LazyLoopRedis builds a NEW underlying client when
        invoked under a different running event loop, isolating per-task
        ``asyncio.run()`` boundaries from cross-loop pool reuse.
        """
        from intellisource.scheduler.lazy_redis import LazyLoopRedis

        builds: list[_LoopBoundFakeRedis] = []

        def fake_from_url(_url: str) -> _LoopBoundFakeRedis:
            client = _LoopBoundFakeRedis()
            builds.append(client)
            return client

        client = LazyLoopRedis("redis://localhost:6379/0", factory=fake_from_url)

        async def _exercise() -> None:
            await client.set("k", "v")

        asyncio.run(_exercise())
        asyncio.run(_exercise())

        assert len(builds) == 2, (
            f"B-037: LazyLoopRedis must build a fresh aioredis client per "
            f"running event loop; got {len(builds)} builds across 2 "
            f"asyncio.run() invocations"
        )

    def test_same_loop_reuses_client(self) -> None:
        """Within a single event loop, LazyLoopRedis must reuse the same
        underlying client (don't pay reconnection cost for every command).
        """
        from intellisource.scheduler.lazy_redis import LazyLoopRedis

        builds: list[_LoopBoundFakeRedis] = []

        def fake_from_url(_url: str) -> _LoopBoundFakeRedis:
            client = _LoopBoundFakeRedis()
            builds.append(client)
            return client

        client = LazyLoopRedis("redis://localhost:6379/0", factory=fake_from_url)

        async def _exercise() -> None:
            await client.set("k1", "v1")
            await client.get("k1")
            await client.delete("k1")

        asyncio.run(_exercise())

        assert len(builds) == 1, (
            f"B-037: LazyLoopRedis must reuse the per-loop client for "
            f"consecutive commands; got {len(builds)} builds"
        )


class TestLazyLoopRedisDelegatesAioredisInterface:
    """LazyLoopRedis must quack like aioredis for IdempotencyGuard,
    CircuitBreaker, RateLimiter, Distributors — the existing callers
    pass it as ``redis=...`` and call set/get/delete/eval/hgetall/hset/
    setex/scan_iter/ping/aclose."""

    @pytest.mark.parametrize(
        "method_name",
        ["set", "get", "delete", "eval", "hgetall", "hset", "setex", "ping"],
    )
    def test_delegates_async_method(self, method_name: str) -> None:
        from intellisource.scheduler.lazy_redis import LazyLoopRedis

        calls: list[tuple[str, tuple, dict]] = []

        class _RecorderRedis:
            def __getattr__(self, name: str) -> Any:
                async def _record(*args: Any, **kwargs: Any) -> str:
                    calls.append((name, args, kwargs))
                    return "ok"

                return _record

        client = LazyLoopRedis(
            "redis://localhost:6379/0", factory=lambda _u: _RecorderRedis()
        )

        async def _exercise() -> None:
            method = getattr(client, method_name)
            await method("key", "value")

        asyncio.run(_exercise())

        assert calls == [(method_name, ("key", "value"), {})], (
            f"B-037: LazyLoopRedis.{method_name} must delegate to the "
            f"underlying aioredis client; got calls={calls}"
        )


# ---------------------------------------------------------------------------
# Regression: IdempotencyGuard survives repeated asyncio.run() with
# LazyLoopRedis (the actual B-031 step-4 failure)
# ---------------------------------------------------------------------------


class TestIdempotencyGuardSurvivesCrossLoop:
    def test_acquire_release_across_two_asyncio_run_calls(self) -> None:
        """B-037 regression: IdempotencyGuard wired with LazyLoopRedis must
        survive acquire-then-release across two separate ``asyncio.run()``
        invocations (mirrors CeleryTasks._run_sync semantics inside
        run_pipeline). Pre-fix, the second call raises
        ``RuntimeError("Event loop is closed")`` because the aioredis
        client's connection pool was bound to the closed loop A.
        """
        from intellisource.scheduler.idempotency import IdempotencyGuard
        from intellisource.scheduler.lazy_redis import LazyLoopRedis

        client = LazyLoopRedis(
            "redis://localhost:6379/0",
            factory=lambda _u: _LoopBoundFakeRedis(),
        )
        guard = IdempotencyGuard(redis=client)

        acquired = asyncio.run(guard.acquire("source-A"))
        assert acquired is True, (
            "B-037: first acquire must return True (fake redis SET NX → True)"
        )

        asyncio.run(guard.release("source-A"))


# ---------------------------------------------------------------------------
# boot.py wiring — _build_redis_client returns LazyLoopRedis, engine uses
# NullPool
# ---------------------------------------------------------------------------


class TestBootRedisFactoryReturnsLazyWrapper:
    def test_build_redis_client_returns_lazy_loop_redis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B-037 GREEN: scheduler.boot._build_redis_client must return a
        ``LazyLoopRedis`` wrapper so all worker-side consumers get the
        per-loop isolation transparently.
        """
        monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")

        from intellisource.scheduler import boot
        from intellisource.scheduler.lazy_redis import LazyLoopRedis

        client = boot._build_redis_client()
        assert isinstance(client, LazyLoopRedis), (
            f"B-037: _build_redis_client must return LazyLoopRedis; "
            f"got {type(client).__name__}"
        )


class TestBootEngineUsesNullPool:
    def test_init_worker_session_factory_uses_null_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B-037 GREEN: worker engine must be constructed with
        ``poolclass=NullPool`` to avoid the engine's connection pool being
        bound to the first ``asyncio.run()`` loop and crashing on the
        second.
        """
        from sqlalchemy.pool import NullPool

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        from intellisource.scheduler import boot

        boot._worker_engine = None
        try:
            boot.init_worker_session_factory()
            assert boot._worker_engine is not None
            # SQLAlchemy 2.x exposes the pool via ``pool`` attribute on the
            # sync core wrapped inside AsyncEngine.
            pool = boot._worker_engine.pool
            assert isinstance(pool, NullPool), (
                f"B-037: worker engine pool must be NullPool to avoid "
                f"cross-loop connection reuse; got {type(pool).__name__}"
            )
        finally:
            boot._worker_engine = None
