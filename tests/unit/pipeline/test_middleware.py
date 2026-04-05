"""Tests for MiddlewareChain and BaseMiddleware (AC-T016-3, AC-T016-4).

Covers:
- AC-T016-3: PipelineEngine supports middleware chain pattern with process(ctx, next) onion model.
- AC-T016-4: Middleware can execute pre/post processing around next(), supports nested composition.
"""

import pytest
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.middleware import BaseMiddleware, MiddlewareChain

# ---------------------------------------------------------------------------
# Test helpers: concrete middleware subclasses
# ---------------------------------------------------------------------------


class TrackingMiddleware(BaseMiddleware):
    """Middleware that records pre/post execution order into context."""

    def __init__(self, name: str):
        self._name = name

    def process(self, ctx: PipelineContext, next_fn):
        # Pre-processing
        log = ctx.get("middleware_log", [])
        log.append(f"{self._name}:before")
        ctx.set("middleware_log", log)

        # Call next middleware/handler
        ctx = next_fn(ctx)

        # Post-processing
        log = ctx.get("middleware_log", [])
        log.append(f"{self._name}:after")
        ctx.set("middleware_log", log)

        return ctx


class FailingMiddleware(BaseMiddleware):
    """Middleware that raises an exception during processing."""

    def process(self, ctx: PipelineContext, next_fn):
        raise RuntimeError("middleware failure")


class ModifyingMiddleware(BaseMiddleware):
    """Middleware that modifies context before and after next."""

    def process(self, ctx: PipelineContext, next_fn):
        # Pre: set a flag
        ctx.set("pre_processed", True)
        ctx = next_fn(ctx)
        # Post: set another flag
        ctx.set("post_processed", True)
        return ctx


class ShortCircuitMiddleware(BaseMiddleware):
    """Middleware that does NOT call next, short-circuiting the chain."""

    def process(self, ctx: PipelineContext, next_fn):
        ctx.set("short_circuited", True)
        return ctx


# ---------------------------------------------------------------------------
# AC-T016-3: BaseMiddleware interface and MiddlewareChain basics
# ---------------------------------------------------------------------------


class TestBaseMiddlewareInterface:
    """AC-T016-3: BaseMiddleware defines process(ctx, next) interface."""

    def test_base_middleware_is_abstract(self):
        """BaseMiddleware should not be instantiable directly."""
        with pytest.raises(TypeError):
            BaseMiddleware()

    def test_subclass_must_implement_process(self):
        """A subclass without process() should raise TypeError on instantiation."""

        class IncompleteMiddleware(BaseMiddleware):
            pass

        with pytest.raises(TypeError):
            IncompleteMiddleware()


class TestMiddlewareChainBasic:
    """AC-T016-3: MiddlewareChain executes middlewares in onion model."""

    def test_empty_chain_passes_through(self):
        """An empty middleware chain should pass context to the core handler unchanged."""
        called = []

        def core_handler(ctx):
            called.append("core")
            return ctx

        chain = MiddlewareChain(middlewares=[], handler=core_handler)
        ctx = PipelineContext()
        result = chain.execute(ctx)
        assert "core" in called
        assert isinstance(result, PipelineContext)

    def test_single_middleware_wraps_handler(self):
        """A single middleware should wrap the core handler with pre/post logic."""

        def core_handler(ctx):
            log = ctx.get("middleware_log", [])
            log.append("core")
            ctx.set("middleware_log", log)
            return ctx

        chain = MiddlewareChain(
            middlewares=[TrackingMiddleware("mw1")],
            handler=core_handler,
        )
        ctx = PipelineContext()
        result = chain.execute(ctx)
        log = result.get("middleware_log")
        assert log == ["mw1:before", "core", "mw1:after"]

    def test_execute_returns_pipeline_context(self):
        """MiddlewareChain.execute() must return a PipelineContext."""

        def core_handler(ctx):
            return ctx

        chain = MiddlewareChain(middlewares=[], handler=core_handler)
        ctx = PipelineContext()
        result = chain.execute(ctx)
        assert isinstance(result, PipelineContext)


# ---------------------------------------------------------------------------
# AC-T016-4: Nested middleware composition (onion model)
# ---------------------------------------------------------------------------


class TestMiddlewareChainNesting:
    """AC-T016-4: Middleware supports nested composition with pre/post processing."""

    def test_nested_onion_order(self):
        """Multiple middlewares should execute in onion order: outer-before, inner-before, core, inner-after, outer-after."""

        def core_handler(ctx):
            log = ctx.get("middleware_log", [])
            log.append("core")
            ctx.set("middleware_log", log)
            return ctx

        chain = MiddlewareChain(
            middlewares=[
                TrackingMiddleware("outer"),
                TrackingMiddleware("inner"),
            ],
            handler=core_handler,
        )
        ctx = PipelineContext()
        result = chain.execute(ctx)
        log = result.get("middleware_log")
        assert log == [
            "outer:before",
            "inner:before",
            "core",
            "inner:after",
            "outer:after",
        ]

    def test_three_level_nesting(self):
        """Three middleware layers should nest correctly."""

        def core_handler(ctx):
            log = ctx.get("middleware_log", [])
            log.append("core")
            ctx.set("middleware_log", log)
            return ctx

        chain = MiddlewareChain(
            middlewares=[
                TrackingMiddleware("L1"),
                TrackingMiddleware("L2"),
                TrackingMiddleware("L3"),
            ],
            handler=core_handler,
        )
        ctx = PipelineContext()
        result = chain.execute(ctx)
        log = result.get("middleware_log")
        assert log == [
            "L1:before",
            "L2:before",
            "L3:before",
            "core",
            "L3:after",
            "L2:after",
            "L1:after",
        ]

    def test_middleware_modifies_context_before_and_after(self):
        """Middleware should be able to modify context both before and after calling next."""

        def core_handler(ctx):
            # Core can see pre-processing
            assert ctx.get("pre_processed") is True
            return ctx

        chain = MiddlewareChain(
            middlewares=[ModifyingMiddleware()],
            handler=core_handler,
        )
        ctx = PipelineContext()
        result = chain.execute(ctx)
        assert result.get("pre_processed") is True
        assert result.get("post_processed") is True

    def test_short_circuit_skips_downstream(self):
        """A middleware that does not call next() should short-circuit the chain."""

        core_called = []

        def core_handler(ctx):
            core_called.append(True)
            return ctx

        chain = MiddlewareChain(
            middlewares=[ShortCircuitMiddleware()],
            handler=core_handler,
        )
        ctx = PipelineContext()
        result = chain.execute(ctx)
        assert result.get("short_circuited") is True
        assert len(core_called) == 0

    def test_middleware_exception_propagates(self):
        """An exception in a middleware should propagate up."""

        def core_handler(ctx):
            return ctx

        chain = MiddlewareChain(
            middlewares=[FailingMiddleware()],
            handler=core_handler,
        )
        ctx = PipelineContext()
        with pytest.raises(RuntimeError, match="middleware failure"):
            chain.execute(ctx)
