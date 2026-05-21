"""Tests for T-083 AC-2 and AC-7: build_agent_runner factory function."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# AC-2: build_agent_runner factory exists and returns AgentRunner
# ---------------------------------------------------------------------------


class TestBuildAgentRunnerFactory:
    """AC-2: build_agent_runner(session_factory, llm_gateway) -> AgentRunner."""

    def test_factory_module_exists(self) -> None:
        """AC-2: intellisource.agent.factory module must exist."""
        import importlib

        mod = importlib.import_module("intellisource.agent.factory")
        assert mod is not None

    def test_build_agent_runner_callable_exists(self) -> None:
        """AC-2: factory module exports a 'build_agent_runner' callable."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )

        assert callable(build_agent_runner)

    def test_build_agent_runner_returns_agent_runner(self) -> None:
        """AC-2: build_agent_runner returns an AgentRunner instance."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )
        from intellisource.agent.runner import AgentRunner

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)

        assert isinstance(runner, AgentRunner), (
            f"Expected AgentRunner, got {type(runner)}"
        )

    def test_build_agent_runner_wires_llm_gateway(self) -> None:
        """AC-2: The returned AgentRunner has the provided llm_gateway wired."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)

        assert runner._llm_gateway is llm_gateway, (
            "AgentRunner._llm_gateway must be the provided llm_gateway"
        )

    def test_build_agent_runner_creates_tool_registry(self) -> None:
        """AC-2: build_agent_runner constructs an AgentToolRegistry internally."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )
        from intellisource.agent.tools import AgentToolRegistry

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)

        assert isinstance(runner._tool_registry, AgentToolRegistry), (
            "AgentRunner._tool_registry must be an AgentToolRegistry instance"
        )


# ---------------------------------------------------------------------------
# AC-7: Returned AgentRunner's registry contains at least 3 tools
# ---------------------------------------------------------------------------


class TestAgentRunnerRegistryTools:
    """AC-7: build_agent_runner registers defaults + atomic tools (>= 3 total)."""

    def test_registry_has_at_least_three_tools(self) -> None:
        """AC-7: tool registry contains >= 3 registered tools after factory call."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)
        tools = runner._tool_registry.list_tools()

        assert len(tools) >= 3, (
            f"Expected at least 3 registered tools, got {len(tools)}: {tools}"
        )

    def test_registry_includes_default_tools(self) -> None:
        """AC-7: registry contains at least one of the known default tools."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)
        tools = set(runner._tool_registry.list_tools())

        known_defaults = {"collect", "process", "distribute", "search"}
        assert tools & known_defaults, (
            f"Expected at least one of {known_defaults} in registry, got {tools}"
        )

    def test_registry_includes_atomic_tools(self) -> None:
        """AC-7: registry contains at least one known atomic tool."""
        from intellisource.agent.factory import (
            build_agent_runner,  # type: ignore[import-untyped]
        )

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)
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
# T-084 R-002: pipeline_engine wired into AgentRunner via factory
# ---------------------------------------------------------------------------


class TestPipelineEngineWiring:
    """T-084 R-002: build_agent_runner wires PipelineEngine loaded from yaml."""

    def test_runner_has_pipeline_engine_set(self) -> None:
        """build_agent_runner returns a runner with _pipeline_engine set (not None)."""
        from intellisource.agent.factory import build_agent_runner
        from intellisource.pipeline.engine import PipelineEngine

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)

        assert runner._pipeline_engine is not None, (
            "_pipeline_engine must be set after factory build"
        )
        engine_type = type(runner._pipeline_engine)
        assert isinstance(runner._pipeline_engine, PipelineEngine), (
            f"_pipeline_engine must be a PipelineEngine, got {engine_type}"
        )

    def test_pipeline_engine_has_processors_from_yaml(self) -> None:
        """build_agent_runner loads content-process.yaml; engine has >=3 processors."""
        from intellisource.agent.factory import build_agent_runner

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(session_factory, llm_gateway)

        engine = runner._pipeline_engine
        assert engine is not None
        processor_count = len(list(engine._processors))
        assert processor_count >= 3, (
            "content-process.yaml has 3 steps; expected >=3 processors,"
            f" got {processor_count}"
        )

    def test_pipeline_engine_wired_with_custom_yaml(self) -> None:
        """build_agent_runner with explicit pipeline_config path wires engine."""
        from intellisource.agent.factory import build_agent_runner

        repo_root = Path(__file__).parents[3]
        yaml_path = str(repo_root / "config" / "pipelines" / "content-process.yaml")

        session_factory = MagicMock()
        llm_gateway = MagicMock()

        runner = build_agent_runner(
            session_factory, llm_gateway, pipeline_config=yaml_path
        )

        engine = runner._pipeline_engine
        assert engine is not None
        assert len(list(engine._processors)) >= 3
