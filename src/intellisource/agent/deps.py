"""Dependency injection container for agent tool execute functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDeps:
    """Dependency container injected into all agent tool execute functions.

    The three ``*_service_factory`` fields are ``Callable[[session], Service]``
    constructed in the composition root. Management tools call them with an open
    session instead of importing the domain-service packages, so the agent layer
    keeps no static edge to source / subscription / pipeline services.

    ``task_dispatcher`` is a ``Callable[[name, params], AsyncResult]`` that
    dispatches a pipeline run onto the task queue, and ``task_chain_repo_factory``
    is a ``Callable[[session], TaskChainRepository]``; together they back the
    ``run_pipeline`` / ``get_task_status`` execution-control tools without the
    agent layer importing scheduler or storage.
    """

    session_factory: Any
    llm_gateway: Any
    pipeline_engine: Any
    search_engine_factory: Any
    collector_registry: Any
    distributor: Any
    source_service_factory: Any = None
    subscription_service_factory: Any = None
    pipeline_service_factory: Any = None
    task_dispatcher: Any = None
    task_chain_repo_factory: Any = None
