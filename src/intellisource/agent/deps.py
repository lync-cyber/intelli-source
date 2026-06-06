"""Dependency injection container for agent tool execute functions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intellisource.collector.registry import CollectorRegistry
    from intellisource.distributor.facade import DistributorFacade
    from intellisource.llm.gateway import LLMGateway
    from intellisource.pipeline.engine import PipelineEngine
    from intellisource.search.hybrid import HybridSearchEngine

#: ``session_factory()`` opens an ``AsyncSession`` usable as an async context
#: manager (``async with tool_deps.session_factory() as session``).
SessionFactory = Callable[[], AbstractAsyncContextManager["AsyncSession"]]
#: ``*_service_factory(session)`` builds a domain service bound to an open
#: session; the concrete service type stays loose so the agent layer keeps no
#: static edge to the source / subscription / pipeline / template packages.
ServiceFactory = Callable[["AsyncSession"], Any]


@dataclass
class ToolDeps:
    """Dependency container injected into all agent tool execute functions.

    The first six fields are required infrastructure handles built in the
    composition root. The ``*_service_factory`` fields are optional
    ``Callable[[session], Service]`` so management tools obtain a session-bound
    service without importing the domain-service packages; ``task_dispatcher``
    dispatches a pipeline run onto the task queue and ``task_chain_repo_factory``
    builds a session-bound TaskChainRepository for the run-status tool.
    """

    session_factory: SessionFactory | None
    llm_gateway: LLMGateway | None
    pipeline_engine: PipelineEngine | None
    search_engine_factory: Callable[[AsyncSession], HybridSearchEngine] | None
    collector_registry: CollectorRegistry | None
    distributor: DistributorFacade | None
    source_service_factory: ServiceFactory | None = None
    subscription_service_factory: ServiceFactory | None = None
    pipeline_service_factory: ServiceFactory | None = None
    template_service_factory: ServiceFactory | None = None
    task_dispatcher: Callable[..., Any] | None = None
    task_chain_repo_factory: ServiceFactory | None = None
