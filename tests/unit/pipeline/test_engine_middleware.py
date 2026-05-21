"""Tests for T-084: PipelineEngine middleware integration and streaming (AC-1 to AC-6).

Covers:
- AC-1: MiddlewareChain before/after onion hooks wired into PipelineEngine.execute()
- AC-2: ConditionalProcessor skip path via PipelineEngine (False=skip, True=execute)
- AC-3: PipelineEngine.execute_stream() as AsyncIterator; execute() batch semantics
- AC-4: config/pipelines/content-process.yaml has >=3 real steps and mode=='batch'
- AC-5: agent/factory.py:build_agent_runner instantiates PipelineEngine internally
- AC-6: Unit tests for 2-processor+1-middleware engine and conditional skip path
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.condition import ConditionalProcessor, ConditionEvaluator
from intellisource.pipeline.context import PipelineContext
from intellisource.pipeline.engine import PipelineEngine
from intellisource.pipeline.middleware import BaseMiddleware, MiddlewareChain

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class _AppendProcessor(BaseProcessor):
    """Appends name to context's 'order' list on each call."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.call_count = 0

    def process(self, context: PipelineContext) -> PipelineContext:
        self.call_count += 1
        order: list[str] = context.get("order", [])
        order.append(self._name)
        context.set("order", order)
        return context


class _TrackingMiddleware(BaseMiddleware):
    """Records before/after hook calls into context's 'mw_log' list."""

    def __init__(self, name: str) -> None:
        self._name = name

    def process(
        self,
        ctx: PipelineContext,
        next_fn: Any,
    ) -> PipelineContext:
        log: list[str] = ctx.get("mw_log", [])
        log.append(f"{self._name}:before")
        ctx.set("mw_log", log)
        ctx = next_fn(ctx)
        log = ctx.get("mw_log", [])
        log.append(f"{self._name}:after")
        ctx.set("mw_log", log)
        return ctx


class _MarkerProcessor(BaseProcessor):
    """Sets 'marker' key in context to self._name when process() is called."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.called = False

    def process(self, context: PipelineContext) -> PipelineContext:
        self.called = True
        context.set("marker", self._name)
        return context


# ===========================================================================
# AC-1: MiddlewareChain before/after hooks wired into PipelineEngine.execute()
# ===========================================================================


class TestAC1MiddlewareHooksInEngine:
    """AC-1: PipelineEngine.execute() runs middleware before/after processors."""

    def test_single_middleware_before_hook_runs_before_processor(self) -> None:
        """before hook of a middleware must fire before any processor runs."""
        proc = _AppendProcessor("processor")
        mw = _TrackingMiddleware("mw1")

        # PipelineEngine must accept a 'middlewares' parameter for this to work
        engine = PipelineEngine(processors=[proc], middlewares=[mw])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        mw_log: list[str] = result.get("mw_log") or []
        order: list[str] = result.get("order") or []
        # before hook must appear before 'processor' in combined ordering evidence
        assert "mw1:before" in mw_log
        assert order == ["processor"]
        # before must precede after
        assert mw_log.index("mw1:before") < mw_log.index("mw1:after")

    def test_single_middleware_after_hook_runs_after_processor(self) -> None:
        """after hook must fire after all processors complete."""
        proc = _AppendProcessor("processor")
        mw = _TrackingMiddleware("mw1")

        engine = PipelineEngine(processors=[proc], middlewares=[mw])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        mw_log: list[str] = result.get("mw_log") or []
        assert "mw1:after" in mw_log

    def test_two_middlewares_onion_order(self) -> None:
        """Two middlewares must wrap in onion order: mw1.before→mw2.before→…→mw2.after→mw1.after."""
        proc = _AppendProcessor("core")
        mw1 = _TrackingMiddleware("mw1")
        mw2 = _TrackingMiddleware("mw2")

        engine = PipelineEngine(processors=[proc], middlewares=[mw1, mw2])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        mw_log: list[str] = result.get("mw_log") or []
        assert mw_log.index("mw1:before") < mw_log.index("mw2:before"), (
            "mw1.before must precede mw2.before"
        )
        assert mw_log.index("mw2:before") < mw_log.index("mw2:after"), (
            "mw2.before must precede mw2.after"
        )
        assert mw_log.index("mw2:after") < mw_log.index("mw1:after"), (
            "mw2.after must precede mw1.after"
        )

    def test_no_middleware_still_executes_processors(self) -> None:
        """PipelineEngine with empty middlewares list still executes processors normally."""
        proc = _AppendProcessor("proc")
        engine = PipelineEngine(processors=[proc], middlewares=[])
        ctx = PipelineContext()
        result = engine.execute(ctx)
        assert result.get("order") == ["proc"]

    def test_middleware_wraps_all_processors_as_unit(self) -> None:
        """Single middleware's before fires before first processor; after fires after last."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        mw = _TrackingMiddleware("mw")

        engine = PipelineEngine(processors=[p1, p2], middlewares=[mw])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        mw_log: list[str] = result.get("mw_log") or []
        order: list[str] = result.get("order") or []
        assert order == ["p1", "p2"]
        assert mw_log[0] == "mw:before"
        assert mw_log[-1] == "mw:after"


# ===========================================================================
# AC-2: ConditionalProcessor skip path via PipelineEngine
# ===========================================================================


class TestAC2ConditionalProcessorInEngine:
    """AC-2: ConditionalProcessor skip (False) and execute (True) paths in PipelineEngine."""

    def test_condition_false_processor_not_called(self) -> None:
        """When condition evaluates False, the wrapped processor's process() is NOT called."""
        inner = _MarkerProcessor("should_skip")
        condition = {"field": "type", "operator": "eq", "value": "article"}
        cond_proc = ConditionalProcessor(condition=condition, if_processor=inner)

        engine = PipelineEngine(processors=[cond_proc], middlewares=[])
        ctx = PipelineContext()
        ctx.set("type", "video")  # does NOT match 'article'
        result = engine.execute(ctx)

        assert inner.called is False, "process() must not be called when condition is False"
        assert result.get("marker") is None

    def test_condition_true_processor_called(self) -> None:
        """When condition evaluates True, the wrapped processor's process() IS called."""
        inner = _MarkerProcessor("should_run")
        condition = {"field": "type", "operator": "eq", "value": "article"}
        cond_proc = ConditionalProcessor(condition=condition, if_processor=inner)

        engine = PipelineEngine(processors=[cond_proc], middlewares=[])
        ctx = PipelineContext()
        ctx.set("type", "article")  # matches
        result = engine.execute(ctx)

        assert inner.called is True, "process() must be called when condition is True"
        assert result.get("marker") == "should_run"

    def test_condition_false_with_else_calls_else(self) -> None:
        """When condition is False and else_processor is set, else branch executes."""
        if_proc = _MarkerProcessor("if_branch")
        else_proc = _MarkerProcessor("else_branch")
        condition = {"field": "type", "operator": "eq", "value": "article"}
        cond_proc = ConditionalProcessor(
            condition=condition,
            if_processor=if_proc,
            else_processor=else_proc,
        )

        engine = PipelineEngine(processors=[cond_proc], middlewares=[])
        ctx = PipelineContext()
        ctx.set("type", "video")
        result = engine.execute(ctx)

        assert if_proc.called is False
        assert else_proc.called is True
        assert result.get("marker") == "else_branch"


# ===========================================================================
# AC-3: execute_stream() is AsyncIterator; execute() is batch
# ===========================================================================


class TestAC3StreamAndBatchPaths:
    """AC-3: execute_stream() yields per-processor; execute() returns final context only."""

    async def test_execute_stream_is_async_iterator(self) -> None:
        """execute_stream() must return an object that implements AsyncIterator protocol."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        engine = PipelineEngine(processors=[p1, p2], middlewares=[])
        ctx = PipelineContext()

        stream = engine.execute_stream(ctx)
        assert isinstance(stream, AsyncIterator), (
            "execute_stream() must return an AsyncIterator"
        )

    async def test_execute_stream_yields_after_each_processor(self) -> None:
        """execute_stream() must yield N times for N processors (one per processor)."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        p3 = _AppendProcessor("p3")
        engine = PipelineEngine(processors=[p1, p2, p3], middlewares=[])
        ctx = PipelineContext()

        yielded: list[PipelineContext] = []
        async for intermediate_ctx in engine.execute_stream(ctx):
            yielded.append(intermediate_ctx)

        assert len(yielded) == 3, f"Expected 3 yields, got {len(yielded)}"

    async def test_execute_stream_each_yield_is_pipeline_context(self) -> None:
        """Every yielded value from execute_stream() must be a PipelineContext."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        engine = PipelineEngine(processors=[p1, p2], middlewares=[])
        ctx = PipelineContext()

        async for intermediate_ctx in engine.execute_stream(ctx):
            assert isinstance(intermediate_ctx, PipelineContext)

    async def test_execute_stream_accumulates_state(self) -> None:
        """Each yielded context reflects cumulative processor results up to that point."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        engine = PipelineEngine(processors=[p1, p2], middlewares=[])
        ctx = PipelineContext()

        snapshots: list[list[str]] = []
        async for intermediate_ctx in engine.execute_stream(ctx):
            order_snapshot = list(intermediate_ctx.get("order") or [])
            snapshots.append(order_snapshot)

        assert snapshots[0] == ["p1"], f"After p1, expected ['p1'], got {snapshots[0]}"
        assert snapshots[1] == ["p1", "p2"], (
            f"After p2, expected ['p1', 'p2'], got {snapshots[1]}"
        )

    def test_execute_batch_returns_single_context(self) -> None:
        """execute() (batch) must return a single PipelineContext, not an iterator."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        engine = PipelineEngine(processors=[p1, p2], middlewares=[])
        ctx = PipelineContext()

        result = engine.execute(ctx)

        assert isinstance(result, PipelineContext), "execute() must return PipelineContext"
        assert result.get("order") == ["p1", "p2"], (
            "execute() must process all processors before returning"
        )

    async def test_execute_stream_empty_processors(self) -> None:
        """execute_stream() with zero processors yields nothing."""
        engine = PipelineEngine(processors=[], middlewares=[])
        ctx = PipelineContext()

        yielded: list[PipelineContext] = []
        async for item in engine.execute_stream(ctx):
            yielded.append(item)

        assert len(yielded) == 0


# ===========================================================================
# AC-4: content-process.yaml steps and mode
# ===========================================================================


class TestAC4ContentProcessYaml:
    """AC-4: config/pipelines/content-process.yaml has >=3 real steps and mode=='batch'."""

    @pytest.fixture
    def yaml_config(self) -> dict[str, Any]:
        config_path = Path("config/pipelines/content-process.yaml")
        # Resolve relative to repo root (two levels up from tests/unit/pipeline/)
        if not config_path.is_absolute():
            repo_root = Path(__file__).parents[3]
            config_path = repo_root / "config" / "pipelines" / "content-process.yaml"
        with config_path.open() as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]

    def test_mode_is_batch(self, yaml_config: dict[str, Any]) -> None:
        """content-process.yaml must have mode == 'batch'."""
        assert yaml_config.get("mode") == "batch", (
            f"Expected mode='batch', got mode='{yaml_config.get('mode')}'"
        )

    def test_steps_has_at_least_three_entries(self, yaml_config: dict[str, Any]) -> None:
        """content-process.yaml must define at least 3 pipeline steps."""
        steps = yaml_config.get("steps", [])
        assert len(steps) >= 3, f"Expected >=3 steps, got {len(steps)}: {steps}"

    def test_steps_include_html_parser(self, yaml_config: dict[str, Any]) -> None:
        """content-process.yaml steps must include an HTMLParser step."""
        steps = yaml_config.get("steps", [])
        step_names = [
            (s.get("processor") or s.get("name") or s) for s in steps
        ]
        html_present = any(
            "html" in str(s).lower() or "HTMLParser" in str(s) for s in step_names
        )
        assert html_present, f"HTMLParser step not found in steps: {step_names}"

    def test_steps_include_content_dedup(self, yaml_config: dict[str, Any]) -> None:
        """content-process.yaml steps must include a ContentDedup step."""
        steps = yaml_config.get("steps", [])
        step_names = [
            (s.get("processor") or s.get("name") or s) for s in steps
        ]
        dedup_present = any(
            "dedup" in str(s).lower() or "ContentDedup" in str(s) for s in step_names
        )
        assert dedup_present, f"ContentDedup step not found in steps: {step_names}"

    def test_steps_include_keyword_tagger(self, yaml_config: dict[str, Any]) -> None:
        """content-process.yaml steps must include a KeywordTagger step."""
        steps = yaml_config.get("steps", [])
        step_names = [
            (s.get("processor") or s.get("name") or s) for s in steps
        ]
        tagger_present = any(
            "keyword" in str(s).lower() or "KeywordTagger" in str(s) for s in step_names
        )
        assert tagger_present, f"KeywordTagger step not found in steps: {step_names}"


# ===========================================================================
# AC-5: build_agent_runner instantiates PipelineEngine internally
# ===========================================================================


class TestAC5FactoryInstantiatesPipelineEngine:
    """AC-5: build_agent_runner must instantiate PipelineEngine with content-process.yaml."""

    def test_pipeline_engine_instantiated_in_factory(self) -> None:
        """build_agent_runner must create a PipelineEngine instance internally."""
        with patch(
            "intellisource.pipeline.engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine_cls.return_value = MagicMock()

            from intellisource.agent.factory import build_agent_runner

            session_factory = MagicMock()
            llm_gateway = MagicMock()
            build_agent_runner(session_factory, llm_gateway)

            assert mock_engine_cls.called, (
                "PipelineEngine() constructor must be called inside build_agent_runner"
            )

    def test_pipeline_engine_call_site_exists_in_src(self) -> None:
        """At least one src/ file must reference PipelineEngine( as a constructor call."""
        result = subprocess.run(
            ["grep", "-rn", "PipelineEngine(", "src/"],
            cwd=str(Path(__file__).parents[3]),
            capture_output=True,
            text=True,
        )
        matches = [
            line for line in result.stdout.splitlines()
            if "test_" not in line and ".pyc" not in line
        ]
        assert len(matches) >= 1, (
            "Expected >=1 PipelineEngine( constructor call in src/, found none.\n"
            f"grep stdout: {result.stdout!r}"
        )


# ===========================================================================
# AC-6: Unit tests — 2 processors + 1 middleware; conditional skip
# ===========================================================================


class TestAC6UnitMiddlewareAndConditionalSkip:
    """AC-6: Direct unit tests for middleware before/after counts and conditional skip."""

    def test_two_processors_one_middleware_before_called_once(self) -> None:
        """With 2 processors and 1 middleware, before hook fires exactly once."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")

        before_count = 0
        after_count = 0

        class _CountingMiddleware(BaseMiddleware):
            def process(self, ctx: PipelineContext, next_fn: Any) -> PipelineContext:
                nonlocal before_count, after_count
                before_count += 1
                ctx = next_fn(ctx)
                after_count += 1
                return ctx

        engine = PipelineEngine(processors=[p1, p2], middlewares=[_CountingMiddleware()])
        ctx = PipelineContext()
        engine.execute(ctx)

        assert before_count == 1, f"before hook must fire exactly once, fired {before_count}"
        assert after_count == 1, f"after hook must fire exactly once, fired {after_count}"

    def test_two_processors_both_called_with_middleware(self) -> None:
        """Both processors run when middleware is present."""
        p1 = _AppendProcessor("p1")
        p2 = _AppendProcessor("p2")
        mw = _TrackingMiddleware("mw")

        engine = PipelineEngine(processors=[p1, p2], middlewares=[mw])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        assert p1.call_count == 1, "p1 must be called exactly once"
        assert p2.call_count == 1, "p2 must be called exactly once"
        assert result.get("order") == ["p1", "p2"]

    def test_conditional_skip_process_not_called_when_false(self) -> None:
        """ConditionalProcessor with False condition: inner process() call_count stays 0."""
        inner = _MarkerProcessor("skip_me")
        condition = {"field": "run", "operator": "eq", "value": True}
        cond_proc = ConditionalProcessor(condition=condition, if_processor=inner)

        engine = PipelineEngine(processors=[cond_proc], middlewares=[])
        ctx = PipelineContext()
        ctx.set("run", False)  # condition is False
        engine.execute(ctx)

        assert inner.called is False, (
            "inner processor.process() must NOT be called when condition is False"
        )

    def test_conditional_execute_process_called_when_true(self) -> None:
        """ConditionalProcessor with True condition: inner process() is called exactly once."""
        inner = _MarkerProcessor("run_me")
        condition = {"field": "run", "operator": "eq", "value": True}
        cond_proc = ConditionalProcessor(condition=condition, if_processor=inner)

        engine = PipelineEngine(processors=[cond_proc], middlewares=[])
        ctx = PipelineContext()
        ctx.set("run", True)  # condition is True
        engine.execute(ctx)

        assert inner.called is True, (
            "inner processor.process() must be called when condition is True"
        )

    def test_middleware_onion_order_with_two_middlewares(self) -> None:
        """Two middlewares must produce exact onion call order."""
        p1 = _AppendProcessor("proc")
        mw1 = _TrackingMiddleware("outer")
        mw2 = _TrackingMiddleware("inner")

        engine = PipelineEngine(processors=[p1], middlewares=[mw1, mw2])
        ctx = PipelineContext()
        result = engine.execute(ctx)

        mw_log: list[str] = result.get("mw_log") or []
        assert mw_log == [
            "outer:before",
            "inner:before",
            "inner:after",
            "outer:after",
        ], f"Unexpected onion order: {mw_log}"
