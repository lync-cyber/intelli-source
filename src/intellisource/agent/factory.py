"""AgentRunner factory — composition root for T-083 AC-2 / AC-7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import intellisource.pipeline.engine as _engine_mod
from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

_DEFAULT_PIPELINE_YAML = (
    Path(__file__).parent.parent.parent.parent
    / "config"
    / "pipelines"
    / "content-process.yaml"
)


class _PassThroughProcessor(BaseProcessor):
    """No-op placeholder when real processor class is unavailable.

    # [ASSUMPTION] yaml step → processor class mapping deferred to T-094
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def process(self, context: PipelineContext) -> PipelineContext:
        return context


def _build_processors_from_config(config: PipelineConfig) -> list[BaseProcessor]:
    """Build a processor list from a PipelineConfig.

    Uses _PassThroughProcessor for each step; concrete class lookup is
    # [ASSUMPTION] yaml step → processor class mapping deferred to T-094
    """
    processors: list[BaseProcessor] = []
    for step in config.steps:
        step_name: str = step.get("processor") or step.get("name") or str(step)
        processors.append(_PassThroughProcessor(step_name))
    return processors


def build_agent_runner(
    session_factory: Any,
    llm_gateway: Any,
    *,
    pipeline_config: str | None = None,
) -> AgentRunner:
    """Build and return a fully-wired AgentRunner."""
    registry = AgentToolRegistry()
    registry.register_defaults()
    registry.register_atomic_tools()

    yaml_path = (
        str(pipeline_config)
        if pipeline_config is not None
        else str(_DEFAULT_PIPELINE_YAML)
    )
    loaded_config = PipelineConfig.from_yaml(yaml_path)
    processors = _build_processors_from_config(loaded_config)
    pipeline_engine = _engine_mod.PipelineEngine(processors=processors)

    return AgentRunner(
        tool_registry=registry,
        llm_gateway=llm_gateway,
        pipeline_engine=pipeline_engine,
    )
