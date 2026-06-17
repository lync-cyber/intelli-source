"""Tests for build_agent_runner factory + get_agent_runner singleton accessor.

Covers AC-2/AC-7: the keyword-only signature and the absence of a
`get_agent_runner()` silent fallback.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _kwargs() -> dict[str, MagicMock]:
    """Return a fresh dict of the five required build_agent_runner kwargs."""
    return {
        "session_factory": MagicMock(),
        "llm_gateway": MagicMock(),
        "collector_registry": MagicMock(),
        "distributor": MagicMock(),
        "search_engine_factory": MagicMock(),
    }


# ---------------------------------------------------------------------------
# AC-2: build_agent_runner factory exists and returns AgentRunner
# ---------------------------------------------------------------------------


class TestBuildAgentRunnerFactory:
    """build_agent_runner(*, ...) -> AgentRunner."""

    def test_factory_module_exists(self) -> None:
        import importlib

        mod = importlib.import_module("intellisource.agent.factory")
        assert hasattr(mod, "build_agent_runner")

    def test_build_agent_runner_callable_exists(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        assert callable(build_agent_runner)

    def test_build_agent_runner_returns_agent_runner(self) -> None:
        from intellisource.agent.factory import build_agent_runner
        from intellisource.agent.runner import AgentRunner

        runner = build_agent_runner(**_kwargs())
        assert isinstance(runner, AgentRunner)

    def test_build_agent_runner_wires_llm_gateway(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        kwargs = _kwargs()
        runner = build_agent_runner(**kwargs)
        assert runner._llm_gateway is kwargs["llm_gateway"]

    def test_build_agent_runner_creates_tool_registry(self) -> None:
        from intellisource.agent.factory import build_agent_runner
        from intellisource.agent.tools import AgentToolRegistry

        runner = build_agent_runner(**_kwargs())
        assert isinstance(runner._tool_registry, AgentToolRegistry)

    def test_build_agent_runner_wires_event_logger_by_default(self) -> None:
        """P1: the runtime event log is wired so pipeline_start / tool_call /
        llm_call / pipeline_complete events actually persist (without an injected
        logger AgentRunner._event_logger stays None and every _emit_* is inert).
        """
        from intellisource.agent.events import PipelineEventLogger
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        assert isinstance(runner._event_logger, PipelineEventLogger)

    def test_build_agent_runner_accepts_explicit_event_logger(self) -> None:
        from intellisource.agent.events import PipelineEventLogger
        from intellisource.agent.factory import build_agent_runner

        custom = PipelineEventLogger(path="custom-pipeline-events.jsonl")
        runner = build_agent_runner(event_logger=custom, **_kwargs())
        assert runner._event_logger is custom


class TestEventLoggerEmitsOnRun:
    """P1: the wired logger actually fires during a run — not merely the right type.

    The isinstance checks above prove the factory injects a logger; this proves
    the loop reaches it, closing the gap where a wired-but-never-called logger
    would still leave the runtime event stream silent.
    """

    @pytest.mark.asyncio
    async def test_run_flexible_emits_pipeline_start_through_wired_logger(
        self,
    ) -> None:
        from unittest.mock import AsyncMock

        from intellisource.agent.events import PipelineEventLogger
        from intellisource.agent.factory import build_agent_runner
        from intellisource.config.pipeline_models import PipelineConfig
        from intellisource.llm.gateway import LLMResult

        class _SpyLogger(PipelineEventLogger):
            def __init__(self) -> None:
                self.starts = 0
                self.llm_calls = 0

            async def pipeline_start(self, **_: object) -> None:
                self.starts += 1

            async def llm_call(self, **_: object) -> None:
                self.llm_calls += 1

            async def tool_call(self, **_: object) -> None:
                return None

            async def pipeline_error(self, **_: object) -> None:
                return None

        spy = _SpyLogger()
        kwargs = _kwargs()
        gw = AsyncMock()
        gw.chat.return_value = LLMResult(
            content="done",
            metadata={"tool_calls": None, "finish_reason": "stop", "usage": {}},
        )
        kwargs["llm_gateway"] = gw
        runner = build_agent_runner(event_logger=spy, **kwargs)
        config = PipelineConfig.from_dict(
            {
                "name": "emit-check",
                "mode": "flexible",
                "tools_allowed": [],
                "tools_denied": [],
                "steps": [],
                "max_steps": 3,
                "on_failure": "skip",
            }
        )

        await runner.run_flexible(config, user_message="hi", session={})

        assert spy.starts >= 1, "pipeline_start must fire through the wired logger"
        assert spy.llm_calls >= 1, "llm_call must fire through the wired logger"


# ---------------------------------------------------------------------------
# AC-7: Returned AgentRunner's registry contains defaults + atomic tools
# ---------------------------------------------------------------------------


class TestAgentRunnerRegistryTools:
    """build_agent_runner registers defaults + atomic tools (>= 3 total)."""

    def test_registry_has_at_least_three_tools(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        tools = runner._tool_registry.list_tools()
        assert len(tools) >= 3, (
            f"Expected at least 3 registered tools, got {len(tools)}: {tools}"
        )

    def test_registry_includes_default_tools(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        tools = set(runner._tool_registry.list_tools())
        known_defaults = {"collect", "process", "distribute", "search"}
        assert tools & known_defaults, (
            f"Expected at least one of {known_defaults} in registry, got {tools}"
        )

    def test_registry_includes_atomic_tools(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        tools = set(runner._tool_registry.list_tools())
        known_atomics = {
            "regex_extract",
            "fingerprint_generate",
            "tfidf_keywords",
            "keyword_tag",
        }
        assert tools & known_atomics, (
            f"Expected at least one of {known_atomics} in registry, got {tools}"
        )


# ---------------------------------------------------------------------------
# PipelineEngine wired into AgentRunner via factory
# ---------------------------------------------------------------------------


class TestPipelineEngineWiring:
    """build_agent_runner wires PipelineEngine loaded from yaml."""

    def test_runner_has_pipeline_engine_set(self) -> None:
        from intellisource.agent.factory import build_agent_runner
        from intellisource.pipeline.engine import PipelineEngine

        runner = build_agent_runner(**_kwargs())
        assert runner._pipeline_engine is not None
        assert isinstance(runner._pipeline_engine, PipelineEngine)

    def test_pipeline_engine_has_processors_from_yaml(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        engine = runner._pipeline_engine
        assert engine is not None
        processor_count = len(list(engine._processors))
        assert processor_count >= 3, (
            "content-process.yaml has 3 steps; expected >=3 processors,"
            f" got {processor_count}"
        )

    def test_pipeline_engine_wired_with_custom_yaml(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        repo_root = Path(__file__).parents[3]
        yaml_path = str(repo_root / "config" / "pipelines" / "content-process.yaml")

        runner = build_agent_runner(pipeline_config=yaml_path, **_kwargs())
        engine = runner._pipeline_engine
        assert engine is not None
        assert len(list(engine._processors)) >= 3


# ---------------------------------------------------------------------------
# build_agent_runner constructs ToolDeps and binds it to AgentRunner
# ---------------------------------------------------------------------------


class TestToolDepsWiring:
    """build_agent_runner must build ToolDeps and wire it into AgentRunner."""

    def test_runner_has_tool_deps_set(self) -> None:
        from intellisource.agent.deps import ToolDeps
        from intellisource.agent.factory import build_agent_runner

        runner = build_agent_runner(**_kwargs())
        assert runner._tool_deps is not None
        assert isinstance(runner._tool_deps, ToolDeps)

    def test_tool_deps_session_factory_bound(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        kwargs = _kwargs()
        runner = build_agent_runner(**kwargs)
        assert runner._tool_deps is not None
        assert runner._tool_deps.session_factory is kwargs["session_factory"]

    def test_tool_deps_llm_gateway_bound(self) -> None:
        from intellisource.agent.factory import build_agent_runner

        kwargs = _kwargs()
        runner = build_agent_runner(**kwargs)
        assert runner._tool_deps is not None
        assert runner._tool_deps.llm_gateway is kwargs["llm_gateway"]

    def test_get_agent_runner_raises_when_uninitialised(self) -> None:
        """get_agent_runner() must raise when no composition root has run yet.

        There is no silent fallback returning a None-wired runner.
        """
        import intellisource.agent.factory as factory_mod
        from intellisource.agent.runner import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        holder.reset()
        try:
            with pytest.raises(RuntimeError, match="AgentRunner not initialised"):
                factory_mod.get_agent_runner()
        finally:
            holder._runner = original

    def test_get_agent_runner_returns_singleton_once_initialised(self) -> None:
        """After install, get_agent_runner() returns the same instance."""
        import intellisource.agent.factory as factory_mod
        from intellisource.agent.factory import build_agent_runner
        from intellisource.agent.runner import get_agent_runner_holder

        holder = get_agent_runner_holder()
        original = holder._runner
        runner = build_agent_runner(**_kwargs())
        holder.install(runner)
        try:
            assert factory_mod.get_agent_runner() is runner
            assert factory_mod.get_agent_runner() is runner
        finally:
            holder._runner = original

    def test_build_agent_runner_rejects_none_deps(self) -> None:
        """build_agent_runner with None deps must raise ValueError."""
        from intellisource.agent.factory import build_agent_runner

        with pytest.raises(ValueError):
            build_agent_runner(  # type: ignore[call-arg]
                session_factory=None,
                llm_gateway=None,
                collector_registry=None,
                distributor=None,
                search_engine_factory=None,
            )


# ---------------------------------------------------------------------------
# AC-014: a pipeline step carrying `condition` is wired as a ConditionalProcessor
# ---------------------------------------------------------------------------


class TestConditionalStepWiring:
    """`_build_processors_from_config` wraps a conditional step's processor."""

    @staticmethod
    def _build(steps: list[dict[str, object]]) -> list[object]:
        from intellisource.agent.factory import _build_processors_from_config
        from intellisource.config.pipeline_models import PipelineConfig

        config = PipelineConfig.from_dict(
            {"name": "t", "mode": "batch", "steps": steps}
        )
        return list(_build_processors_from_config(config))

    def test_step_without_condition_builds_bare_processor(self) -> None:
        from intellisource.pipeline.condition import ConditionalProcessor
        from intellisource.pipeline.processors.dedup import ContentDedup

        procs = self._build([{"processor": "ContentDedup"}])

        assert isinstance(procs[0], ContentDedup)
        assert not isinstance(procs[0], ConditionalProcessor)

    def test_step_with_condition_wraps_in_conditional_processor(self) -> None:
        from intellisource.pipeline.condition import ConditionalProcessor
        from intellisource.pipeline.processors.dedup import ContentDedup

        condition = {"field": "content_type", "operator": "eq", "value": "article"}
        procs = self._build([{"processor": "ContentDedup", "condition": condition}])

        wrapped = procs[0]
        assert isinstance(wrapped, ConditionalProcessor)
        assert isinstance(wrapped._if_processor, ContentDedup)
        assert wrapped._condition == condition
        assert wrapped._else_processor is None
