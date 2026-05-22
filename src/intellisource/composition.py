"""Composition root shared by FastAPI and Celery worker processes.

This module is the single place that wires concrete dependencies into the
`AgentRunner` / `CeleryTasks` / `ToolDeps` objects that the API and Worker
processes consume. Both processes import from here, ensuring identical
wire-up across the deployment.

Public surface:

- `PipelineLoader` — thin protocol that resolves pipeline names to
  `PipelineConfig` instances.
- `DistributorFacade` — `distribute()` protocol stub used by the
  `_distribute_execute` agent tool. The real subscription-matching /
  channel-dispatching implementation is delivered by T-097
  (`distributor/facade.py`); this module provides a degraded fallback so
  T-095 can wire dependencies without crashing.
- `WorkerComposition` — bundle returned by `build_worker_composition`.
- `build_llm_gateway` / `build_pipeline_loader` /
  `build_collector_registry` / `build_distributor_facade` /
  `build_search_engine_factory` — small assembly helpers shared by both
  processes.
- `build_worker_composition` — Worker entry point. Called from
  `scheduler/boot.py:worker_init_handler`.
- `build_api_composition` — API entry point. Called from
  `intellisource.main._lifespan`. Writes the same composition to
  `app.state.agent_runner` plus a small set of auxiliary handles
  (`celery_app`, `pipeline_loader`).
- `SOURCE_TYPE_TO_PIPELINE` — mapping used by `/tasks/collect` to pick a
  pipeline name from a Source row's `type` column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from intellisource.agent.pipeline import PipelineConfig
from intellisource.agent.runner import AgentRunner
from intellisource.agent.tools import load_pipeline_config
from intellisource.collector.adapters.api import APICollector
from intellisource.collector.adapters.rss import RSSCollector
from intellisource.collector.adapters.web import WebCollector
from intellisource.collector.registry import CollectorRegistry
from intellisource.llm.circuit_breaker import CircuitBreaker
from intellisource.llm.gateway import LLMGateway
from intellisource.llm.priority_queue import PriorityQueue
from intellisource.search.hybrid import HybridSearchEngine

if TYPE_CHECKING:
    from fastapi import FastAPI

    from intellisource.storage.database import DatabaseManager


SOURCE_TYPE_TO_PIPELINE: dict[str, str] = {
    "rss": "scheduled-collect",
    "api": "scheduled-collect",
    "web": "scheduled-collect",
}
"""Source.type → pipeline yaml name. Used by `/tasks/collect` send_task."""


# ---------------------------------------------------------------------------
# PipelineLoader
# ---------------------------------------------------------------------------


class PipelineLoader:
    """Resolve a pipeline yaml name to a `PipelineConfig` instance.

    Wraps `intellisource.agent.tools.load_pipeline_config` so that the
    `CeleryTasks.run_pipeline` consumer can hold a stable, mockable
    dependency instead of a free function.
    """

    def load(self, name: str) -> PipelineConfig:
        return load_pipeline_config(name)


def build_pipeline_loader() -> PipelineLoader:
    return PipelineLoader()


# ---------------------------------------------------------------------------
# DistributorFacade — protocol stub. T-097 ships the real implementation.
# ---------------------------------------------------------------------------


class DistributorFacade:
    """Distribution orchestrator protocol consumed by the `distribute` tool.

    The full implementation (subscription matching → quiet-hours / frequency
    / dedup gating → channel dispatch → push-record persistence) is delivered
    by T-097 in `src/intellisource/distributor/facade.py`. T-095 only needs
    a non-None object with a `distribute()` coroutine so the agent tool can
    be wired without ToolDeps holding a `None` slot.

    Until T-097 lands, this stub returns a `status: pending` envelope. It
    does NOT return `status: degraded` — degraded is reserved for the case
    where the dependency is missing entirely.
    """

    async def distribute(
        self,
        *,
        content_id: str,
        subscription_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "status": "pending",
            "reason": "DistributorFacade stub — T-097 ships real implementation",
            "content_id": content_id,
            "subscription_id": subscription_id,
        }


def build_distributor_facade(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
) -> DistributorFacade:
    """Build a DistributorFacade.

    T-095 returns a stub instance; T-097 replaces this with the production
    facade that consults SubscriptionMatcher and channel-specific
    `BaseDistributor` subclasses.
    """
    return DistributorFacade()


# ---------------------------------------------------------------------------
# Collector registry
# ---------------------------------------------------------------------------


def build_collector_registry() -> CollectorRegistry:
    """Register the three first-party collector adapters (RSS / API / Web)."""
    registry = CollectorRegistry()
    registry.register("rss", RSSCollector)
    registry.register("api", APICollector)
    registry.register("web", WebCollector)
    return registry


# ---------------------------------------------------------------------------
# LLM gateway
# ---------------------------------------------------------------------------


def build_llm_gateway(redis_client: Any) -> LLMGateway:
    """Assemble LLMGateway with its CircuitBreaker and PriorityQueue.

    Mirrors the wire-up previously inlined in `intellisource.main._lifespan`
    so the Worker process can produce an identical LLMGateway.
    """
    circuit_breaker = CircuitBreaker(redis=redis_client)
    priority_queue = PriorityQueue()
    return LLMGateway(
        circuit_breaker=circuit_breaker,
        priority_queue=priority_queue,
    )


# ---------------------------------------------------------------------------
# HybridSearchEngine factory
# ---------------------------------------------------------------------------


def build_search_engine_factory() -> Callable[[AsyncSession], HybridSearchEngine]:
    """Return a session-scoped factory for HybridSearchEngine.

    HybridSearchEngine takes an AsyncSession directly (not a session_factory)
    because each search request needs its own session lifecycle. The
    `_search_execute` agent tool opens a session via tool_deps.session_factory
    then calls this factory to wrap it.
    """

    def _factory(session: AsyncSession) -> HybridSearchEngine:
        return HybridSearchEngine(session)

    return _factory


# ---------------------------------------------------------------------------
# WorkerComposition + assembly entry points
# ---------------------------------------------------------------------------


@dataclass
class WorkerComposition:
    """Bundle of dependencies returned by `build_worker_composition`."""

    agent_runner: AgentRunner
    pipeline_loader: PipelineLoader
    collector_registry: CollectorRegistry
    distributor: DistributorFacade
    session_factory: async_sessionmaker[AsyncSession]


@dataclass
class _DepsBundle:
    """Bundle of the four dependencies shared by Worker and API compositions."""

    llm_gateway: LLMGateway
    collector_registry: CollectorRegistry
    distributor: DistributorFacade
    search_engine_factory: Callable[[AsyncSession], HybridSearchEngine]


def _build_deps_bundle(session_factory: Any, redis_client: Any) -> _DepsBundle:
    """Assemble the four ToolDeps-bound dependencies shared by both processes."""
    return _DepsBundle(
        llm_gateway=build_llm_gateway(redis_client),
        collector_registry=build_collector_registry(),
        distributor=build_distributor_facade(session_factory, redis_client),
        search_engine_factory=build_search_engine_factory(),
    )


def _install_agent_runner(session_factory: Any, bundle: _DepsBundle) -> AgentRunner:
    """Build an AgentRunner from the deps bundle and install it as the
    `intellisource.agent.factory` module-level singleton so legacy callers
    of `get_agent_runner()` keep resolving to the same instance both
    processes assembled.
    """
    # Import here to avoid circular import via agent.factory.
    from intellisource.agent import factory as agent_factory

    runner = agent_factory.build_agent_runner(
        session_factory=session_factory,
        llm_gateway=bundle.llm_gateway,
        collector_registry=bundle.collector_registry,
        distributor=bundle.distributor,
        search_engine_factory=bundle.search_engine_factory,
    )
    agent_factory._agent_runner = runner
    return runner


def build_worker_composition(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
) -> WorkerComposition:
    """Wire up the full Worker-side composition graph.

    Called from `scheduler/boot.py:worker_init_handler` on Celery worker
    process init. Returns the `WorkerComposition` bundle the handler then
    feeds into `build_celery_tasks`.

    Side effect: installs the assembled `AgentRunner` as the
    `intellisource.agent.factory` module-level singleton so legacy callers
    of `get_agent_runner()` keep working.
    """
    bundle = _build_deps_bundle(session_factory, redis_client)
    agent_runner = _install_agent_runner(session_factory, bundle)
    pipeline_loader = build_pipeline_loader()
    return WorkerComposition(
        agent_runner=agent_runner,
        pipeline_loader=pipeline_loader,
        collector_registry=bundle.collector_registry,
        distributor=bundle.distributor,
        session_factory=session_factory,
    )


def build_api_composition(
    app: FastAPI,
    db_manager: DatabaseManager,
    redis_client: Any,
) -> None:
    """Wire up the API-side composition graph and install it on `app.state`.

    Called from `intellisource.main._lifespan`. Writes the assembled
    `celery_app` / `llm_gateway` / `pipeline_loader` / `agent_runner` onto
    `app.state` so request handlers and middleware can reach them via
    `request.app.state.<attr>`.

    The API process and Worker process share the SAME Celery() instance via
    the module-level `intellisource.scheduler.celery_app.celery_app` — this
    is what closes CR-012 (dual-singleton).
    """
    # Trigger @celery_app.task(name="run_pipeline") registration so the API
    # process can `send_task("run_pipeline", ...)` and hit the same task
    # definition the Worker consumes.
    import intellisource.scheduler.tasks  # noqa: F401  registers run_pipeline
    from intellisource.scheduler.celery_app import celery_app as module_celery_app

    app.state.celery_app = module_celery_app

    # DatabaseManager exposes get_session() (an async context manager) but
    # not a sessionmaker. Agent tools invoke `tool_deps.session_factory()`
    # then `async with` on the result, so we adapt get_session into a
    # callable returning the existing context manager.
    session_factory = _DatabaseManagerSessionFactory(db_manager)

    bundle = _build_deps_bundle(session_factory, redis_client)
    agent_runner = _install_agent_runner(session_factory, bundle)
    pipeline_loader = build_pipeline_loader()

    app.state.llm_gateway = bundle.llm_gateway
    app.state.pipeline_loader = pipeline_loader
    app.state.agent_runner = agent_runner


class _DatabaseManagerSessionFactory:
    """Adapter that exposes `DatabaseManager.get_session()` as a callable.

    Tool execute functions invoke `tool_deps.session_factory()` and then
    `async with` on the result. `DatabaseManager.get_session()` is already
    an async context manager, so we just forward the call.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def __call__(self) -> Any:
        return self._db_manager.get_session()
