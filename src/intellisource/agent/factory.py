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
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import AgentToolRegistry
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.registry import get_processor

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intellisource.collector.registry import CollectorRegistry
    from intellisource.distributor.facade import DistributorFacade
    from intellisource.llm.gateway import LLMGateway
    from intellisource.search.hybrid import HybridSearchEngine


_DEFAULT_PIPELINE_YAML = (
    Path(__file__).parent.parent.parent.parent
    / "config"
    / "pipelines"
    / "content-process.yaml"
)


def _build_processors_from_config(
    config: PipelineConfig,
    llm_gateway: LLMGateway | None = None,
) -> list[BaseProcessor]:
    processors: list[BaseProcessor] = []
    for step in config.steps:
        step_name: str = step.get("processor") or step.get("name") or str(step)
        cls = get_processor(step_name)
        params: dict[str, Any] = dict(step.get("params") or {})
        if getattr(cls, "_NEEDS_LLM_GATEWAY", False) and "llm_gateway" not in params:
            params["llm_gateway"] = llm_gateway
        processors.append(cls(**params))
    return processors


def get_agent_runner() -> AgentRunner:
    """Return the process-wide AgentRunner singleton.

    Delegates to `intellisource.composition.get_agent_runner_holder().get()`.
    Raises CompositionNotInitialisedError (also a RuntimeError) when the
    composition root has not yet installed an instance — Worker processes
    must run `build_worker_composition` first; API processes rely on
    `build_api_composition` from FastAPI lifespan startup.
    """
    # Lazy import — composition imports from this module at runtime.
    from intellisource.composition import get_agent_runner_holder

    return get_agent_runner_holder().get()


def build_agent_runner(
    *,
    session_factory: Any,
    llm_gateway: LLMGateway,
    collector_registry: CollectorRegistry,
    distributor: DistributorFacade,
    search_engine_factory: Callable[[AsyncSession], HybridSearchEngine],
    pipeline_config: str | None = None,
    source_service_factory: Any = None,
    subscription_service_factory: Any = None,
    pipeline_service_factory: Any = None,
    template_service_factory: Any = None,
    task_dispatcher: Any = None,
    task_chain_repo_factory: Any = None,
) -> AgentRunner:
    """Build a fully-wired AgentRunner.

    The five infrastructure dependencies are required keyword arguments; passing
    `None` raises CompositionError (also a ValueError) so wiring bugs fail loudly
    at composition time. The three ``*_service_factory`` arguments are optional
    ``Callable[[session], Service]`` that back the management (CRUD) tools;
    ``task_dispatcher`` and ``task_chain_repo_factory`` back the run-trigger /
    run-status execution-control tools.
    """
    # Lazy import — composition imports build_agent_runner from this module.
    from intellisource.composition import CompositionError

    if session_factory is None:
        raise CompositionError("session_factory is required (got None)")
    if llm_gateway is None:
        raise CompositionError("llm_gateway is required (got None)")
    if collector_registry is None:
        raise CompositionError("collector_registry is required (got None)")
    if distributor is None:
        raise CompositionError("distributor is required (got None)")
    if search_engine_factory is None:
        raise CompositionError("search_engine_factory is required (got None)")

    registry = AgentToolRegistry()
    registry.register_defaults()
    registry.register_atomic_tools()
    registry.register_management_tools()

    resolved_yaml = (
        Path(pipeline_config) if pipeline_config is not None else _DEFAULT_PIPELINE_YAML
    )
    if not resolved_yaml.exists():
        raise FileNotFoundError(f"Pipeline yaml not found: {resolved_yaml.resolve()}")
    loaded_config = PipelineConfig.from_yaml(str(resolved_yaml))
    processors = _build_processors_from_config(loaded_config, llm_gateway=llm_gateway)
    pipeline_engine = _engine_mod.PipelineEngine(processors=processors)

    tool_deps = ToolDeps(
        session_factory=session_factory,
        llm_gateway=llm_gateway,
        pipeline_engine=pipeline_engine,
        search_engine_factory=search_engine_factory,
        collector_registry=collector_registry,
        distributor=distributor,
        source_service_factory=source_service_factory,
        subscription_service_factory=subscription_service_factory,
        pipeline_service_factory=pipeline_service_factory,
        template_service_factory=template_service_factory,
        task_dispatcher=task_dispatcher,
        task_chain_repo_factory=task_chain_repo_factory,
    )

    return AgentRunner(
        tool_registry=registry,
        llm_gateway=llm_gateway,
        pipeline_engine=pipeline_engine,
        tool_deps=tool_deps,
    )
