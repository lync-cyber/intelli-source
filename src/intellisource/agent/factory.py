"""AgentRunner factory — composition root for T-083 AC-2 / AC-7."""

from __future__ import annotations

from typing import Any

from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry


def build_agent_runner(
    session_factory: Any,
    llm_gateway: Any,
    *,
    pipeline_config: Any = None,
) -> AgentRunner:
    """Build and return a fully-wired AgentRunner.

    Constructs an AgentToolRegistry, registers default tools and atomic
    tools, then returns an AgentRunner bound to the provided llm_gateway.
    """
    registry = AgentToolRegistry()
    registry.register_defaults()
    registry.register_atomic_tools()

    return AgentRunner(
        tool_registry=registry,
        llm_gateway=llm_gateway,
    )
