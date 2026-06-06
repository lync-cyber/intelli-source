"""Composition root shared by FastAPI and Celery worker processes.

This package is the single place that wires concrete dependencies into the
``AgentRunner`` / ``CeleryTasks`` / ``ToolDeps`` objects that the API and Worker
processes consume. Both processes import from here, ensuring identical wire-up
across the deployment.

Submodules:

- ``builders`` — small ``build_*`` assembly helpers (LLM gateway, collector
  registry, distributor facade, search-engine factory, pipeline loader).
- ``deps`` — the shared four-dependency bundle and AgentRunner install.
- ``worker`` — ``build_worker_composition`` Worker entry point.
- ``api`` — ``build_api_composition`` API entry point + ``app.state`` install.
- ``app_state`` — typed ``AppState`` view over ``request.app.state``.
"""

from __future__ import annotations

from intellisource.composition.api import (
    _install_observability_state,
    build_api_composition,
)
from intellisource.composition.app_state import (
    AppState,
    get_app_state,
    validate_app_state,
)
from intellisource.composition.builders import (
    PipelineLoader,
    build_collector_registry,
    build_distributor_facade,
    build_llm_gateway,
    build_pipeline_loader,
    build_search_engine_factory,
)
from intellisource.composition.deps import _build_deps_bundle, _install_agent_runner
from intellisource.composition.worker import (
    WorkerComposition,
    build_worker_composition,
    hydrate_worker_template_registry,
)

__all__ = [
    "AppState",
    "PipelineLoader",
    "WorkerComposition",
    "_build_deps_bundle",
    "_install_agent_runner",
    "_install_observability_state",
    "build_api_composition",
    "build_collector_registry",
    "build_distributor_facade",
    "build_llm_gateway",
    "build_pipeline_loader",
    "build_search_engine_factory",
    "build_worker_composition",
    "get_app_state",
    "hydrate_worker_template_registry",
    "validate_app_state",
]
