"""Shared dependency bundle assembled identically for both processes.

``_build_deps_bundle`` constructs the four ToolDeps-bound dependencies and
``_install_agent_runner`` builds the AgentRunner from them and installs it into
the process-wide holder, so API and Worker resolve to the same instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.agent.runner import AgentRunner, get_agent_runner_holder
from intellisource.collector.registry import CollectorRegistry
from intellisource.composition.builders import (
    build_collector_registry,
    build_distributor_facade,
    build_llm_gateway,
    build_search_engine_factory,
)
from intellisource.distributor.facade import DistributorFacade
from intellisource.llm.gateway import LLMGateway
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.search.hybrid import HybridSearchEngine
from intellisource.source.service import SourceConfigService
from intellisource.subscription.service import SubscriptionService
from intellisource.template.service import TemplateService


@dataclass
class _DepsBundle:
    """Bundle of the four dependencies shared by Worker and API compositions."""

    llm_gateway: LLMGateway
    collector_registry: CollectorRegistry
    distributor: DistributorFacade
    search_engine_factory: Callable[[AsyncSession], HybridSearchEngine]


def _build_deps_bundle(
    session_factory: Any, redis_client: Any, celery_app: Any = None
) -> _DepsBundle:
    """Assemble the four ToolDeps-bound dependencies shared by both processes."""
    del celery_app  # retained in signature for Worker init call-site stability
    llm_gateway = build_llm_gateway(redis_client, session_factory=session_factory)
    return _DepsBundle(
        llm_gateway=llm_gateway,
        collector_registry=build_collector_registry(redis_client),
        distributor=build_distributor_facade(
            session_factory, redis_client, llm_gateway=llm_gateway
        ),
        search_engine_factory=build_search_engine_factory(),
    )


def _install_agent_runner(session_factory: Any, bundle: _DepsBundle) -> AgentRunner:
    """Build an AgentRunner from the deps bundle and install it into the
    process-wide AgentRunnerHolder so `get_agent_runner_holder().get()`
    (and the legacy `agent.factory.get_agent_runner()` wrapper) resolve to
    the same instance both processes assembled.
    """
    # Import here to avoid circular import via agent.factory.
    from intellisource.agent import factory as agent_factory
    from intellisource.scheduler.celery_app import celery_app
    from intellisource.scheduler.dispatch import send_task_with_trace
    from intellisource.storage.repositories.task_chain import TaskChainRepository

    def _dispatch_pipeline_run(name: str, params: dict[str, Any]) -> Any:
        """Dispatch a ``run_pipeline`` task on the shared Celery app."""
        return send_task_with_trace(
            "run_pipeline",
            kwargs={"pipeline_name": name, "params": params},
            celery_instance=celery_app,
        )

    runner = agent_factory.build_agent_runner(
        session_factory=session_factory,
        llm_gateway=bundle.llm_gateway,
        collector_registry=bundle.collector_registry,
        distributor=bundle.distributor,
        search_engine_factory=bundle.search_engine_factory,
        source_service_factory=lambda session: SourceConfigService(session),
        subscription_service_factory=lambda session: SubscriptionService(session),
        pipeline_service_factory=lambda session: PipelineDefinitionService(session),
        template_service_factory=lambda session: TemplateService(session),
        task_dispatcher=_dispatch_pipeline_run,
        task_chain_repo_factory=lambda session: TaskChainRepository(session),
    )
    get_agent_runner_holder().install(runner)
    return runner
