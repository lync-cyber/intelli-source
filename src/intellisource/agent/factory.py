"""AgentRunner factory — composition entry-point.

The real wiring lives in `intellisource.composition.build_worker_composition`
/ `build_api_composition`. This module provides the low-level
`build_agent_runner` that those callers use, plus the legacy
`get_agent_runner()` module-level singleton accessor.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import intellisource.pipeline.engine as _engine_mod
from intellisource.agent.deps import ToolDeps
from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intellisource.collector.registry import CollectorRegistry
    from intellisource.composition import DistributorFacade
    from intellisource.llm.gateway import LLMGateway
    from intellisource.search.hybrid import HybridSearchEngine


_DEFAULT_PIPELINE_YAML = (
    Path(__file__).parent.parent.parent.parent
    / "config"
    / "pipelines"
    / "content-process.yaml"
)


class _PassThroughProcessor(BaseProcessor):
    """No-op placeholder for processor steps that have not been mapped yet.

    T-096 introduces a real PROCESSOR_REGISTRY and removes this fallback.
    Kept for now so `content-process.yaml` loads at startup without raising;
    once T-096 ships, the `_build_processors_from_config` mapping switches
    to fail-fast on unknown processor names.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def process(self, context: PipelineContext) -> PipelineContext:
        return context


def _build_processors_from_config(config: PipelineConfig) -> list[BaseProcessor]:
    processors: list[BaseProcessor] = []
    for step in config.steps:
        step_name: str = step.get("processor") or step.get("name") or str(step)
        processors.append(_PassThroughProcessor(step_name))
    return processors


_agent_runner: AgentRunner | None = None


def get_agent_runner() -> AgentRunner:
    """Return the module-level AgentRunner singleton.

    Raises RuntimeError when the composition root has not yet installed an
    instance. Callers in the Worker process must run
    `intellisource.composition.build_worker_composition` first; callers in
    the API process rely on `intellisource.composition.build_api_composition`
    invoked during FastAPI lifespan startup.
    """
    if _agent_runner is None:
        raise RuntimeError(
            "AgentRunner not initialised; call build_worker_composition() or "
            "build_api_composition() first"
        )
    return _agent_runner


def build_agent_runner(
    *,
    session_factory: Any,
    llm_gateway: LLMGateway,
    collector_registry: CollectorRegistry,
    distributor: DistributorFacade,
    search_engine_factory: Callable[[AsyncSession], HybridSearchEngine],
    pipeline_config: str | None = None,
) -> AgentRunner:
    """Build a fully-wired AgentRunner.

    All dependencies are required keyword arguments. Passing `None` for any
    of them raises ValueError so wiring bugs fail loudly at composition
    time rather than silently producing degraded tool responses at runtime.
    """
    if session_factory is None:
        raise ValueError("session_factory is required (got None)")
    if llm_gateway is None:
        raise ValueError("llm_gateway is required (got None)")
    if collector_registry is None:
        raise ValueError("collector_registry is required (got None)")
    if distributor is None:
        raise ValueError("distributor is required (got None)")
    if search_engine_factory is None:
        raise ValueError("search_engine_factory is required (got None)")

    registry = AgentToolRegistry()
    registry.register_defaults()
    registry.register_atomic_tools()

    resolved_yaml = (
        Path(pipeline_config) if pipeline_config is not None else _DEFAULT_PIPELINE_YAML
    )
    if not resolved_yaml.exists():
        raise FileNotFoundError(f"Pipeline yaml not found: {resolved_yaml.resolve()}")
    loaded_config = PipelineConfig.from_yaml(str(resolved_yaml))
    processors = _build_processors_from_config(loaded_config)
    pipeline_engine = _engine_mod.PipelineEngine(processors=processors)

    tool_deps = ToolDeps(
        session_factory=session_factory,
        llm_gateway=llm_gateway,
        pipeline_engine=pipeline_engine,
        search_engine=search_engine_factory,
        collector_registry=collector_registry,
        distributor=distributor,
    )

    return AgentRunner(
        tool_registry=registry,
        llm_gateway=llm_gateway,
        pipeline_engine=pipeline_engine,
        tool_deps=tool_deps,
    )
