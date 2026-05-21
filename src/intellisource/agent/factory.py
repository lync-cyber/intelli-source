"""AgentRunner factory — composition root for T-083 AC-2 / AC-7."""

from __future__ import annotations

from typing import Any

import intellisource.pipeline.engine as _engine_mod
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry


def build_agent_runner(
    session_factory: Any,
    llm_gateway: Any,
    *,
    pipeline_config: Any = None,
) -> AgentRunner:
    """Build and return a fully-wired AgentRunner."""
    registry = AgentToolRegistry()
    registry.register_defaults()
    registry.register_atomic_tools()

    _pipeline_engine = _engine_mod.PipelineEngine(processors=[])

    return AgentRunner(
        tool_registry=registry,
        llm_gateway=llm_gateway,
    )
