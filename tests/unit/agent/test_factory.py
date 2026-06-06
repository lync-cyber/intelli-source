"""Tests for build_agent_runner factory + get_agent_runner singleton accessor.

Originally written for T-083 AC-2/AC-7. Updated by T-095 to reflect the
keyword-only signature and the removal of `get_agent_runner()` silent
fallback — those legacy behaviours were the bugs documented in CR-001.
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

        Replaces the legacy `test_get_agent_runner_no_args_backward_compat` —
        the silent fallback that returned a None-wired runner was CR-001
        and is now removed.
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
        """build_agent_runner with None deps must raise ValueError.

        Replaces the legacy `test_build_agent_runner_none_deps_allowed` —
        accepting None was the silent-degradation bug behind CR-001.
        """
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
