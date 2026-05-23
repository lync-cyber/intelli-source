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

import os
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
from intellisource.core.errors import ErrorCategory, IntelliSourceError
from intellisource.distributor.channels.email import EmailDistributor
from intellisource.distributor.channels.wechat import WeChatDistributor
from intellisource.distributor.channels.wework import WeWorkDistributor
from intellisource.distributor.facade import DistributorFacade
from intellisource.distributor.matcher import SubscriptionMatcher
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
# Composition errors (arch §5.3 — IntelliSourceError hierarchy)
# ---------------------------------------------------------------------------


class CompositionError(IntelliSourceError, ValueError):
    """Raised when the composition root receives invalid dependencies.

    Multiple inheritance keeps `isinstance(exc, ValueError)` true so callers
    that catch the built-in `ValueError` (and existing tests) still match.
    """

    def __init__(self, message: str) -> None:
        IntelliSourceError.__init__(
            self,
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint=(
                "Wire dependencies via build_worker_composition() or "
                "build_api_composition()"
            ),
        )


class CompositionNotInitialisedError(IntelliSourceError, RuntimeError):
    """Raised when a process-wide singleton is read before composition root ran.

    Multiple inheritance preserves `isinstance(exc, RuntimeError)` for callers
    catching the built-in.
    """

    def __init__(self, message: str) -> None:
        IntelliSourceError.__init__(
            self,
            message,
            category=ErrorCategory.UNRECOVERABLE,
            recovery_hint=(
                "Call build_worker_composition() (Worker) or "
                "build_api_composition() (API) before reaching this code path"
            ),
        )


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


def build_distributor_facade(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
) -> DistributorFacade:
    """Build a DistributorFacade with all three distribution channels.

    Reads channel credentials from environment variables.  Missing required
    variables cause a ValueError at startup (hard-fail by design).
    """
    wechat = WeChatDistributor.from_env(redis=redis_client)
    wework = WeWorkDistributor.from_env(redis=redis_client)
    email = EmailDistributor.from_env()
    matcher = SubscriptionMatcher()
    channels: dict[str, Any] = {
        "wechat": wechat,
        "wework": wework,
        "email": email,
    }
    return DistributorFacade(
        session_factory=session_factory,
        matcher=matcher,
        channels=channels,
    )


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
# AgentRunner singleton holder — replaces the dead `agent_factory._agent_runner`
# module-level state. The holder is process-wide; both Worker and API
# composition roots install into the same global instance so legacy
# `get_agent_runner()` callers resolve to whichever runner was built last.
# ---------------------------------------------------------------------------


class AgentRunnerHolder:
    """Mutable single-slot container for the process-wide AgentRunner.

    Owned by the composition root. `install()` puts the assembled runner in;
    `get()` reads it (raising CompositionNotInitialisedError when empty);
    `reset()` clears the slot (test fixture support only).
    """

    def __init__(self) -> None:
        self._runner: AgentRunner | None = None

    def install(self, runner: AgentRunner) -> None:
        self._runner = runner

    def get(self) -> AgentRunner:
        if self._runner is None:
            raise CompositionNotInitialisedError(
                "AgentRunner not initialised; call build_worker_composition() "
                "or build_api_composition() first"
            )
        return self._runner

    def reset(self) -> None:
        self._runner = None

    @property
    def installed(self) -> bool:
        return self._runner is not None


_global_agent_runner_holder = AgentRunnerHolder()
"""Process-wide AgentRunner holder. Read via get_agent_runner_holder()."""


def get_agent_runner_holder() -> AgentRunnerHolder:
    """Return the process-wide AgentRunnerHolder singleton."""
    return _global_agent_runner_holder


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
    """Build an AgentRunner from the deps bundle and install it into the
    process-wide AgentRunnerHolder so `get_agent_runner_holder().get()`
    (and the legacy `agent.factory.get_agent_runner()` wrapper) resolve to
    the same instance both processes assembled.
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
    _global_agent_runner_holder.install(runner)
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

    _install_webhook_state(app, redis_client=redis_client)
    app.state.background_tasks = set()
    _install_observability_state(app, db_manager=db_manager, redis_client=redis_client)


def _install_observability_state(
    app: FastAPI, *, db_manager: DatabaseManager, redis_client: Any
) -> None:
    """Wire health_checker / metrics_collector / config_version_manager state.

    AC-T099-5 — replaces the placeholder stubs in `api/routers/system.py` with
    a real `HealthChecker` (checks: db, redis, celery), the singleton
    `MetricsCollector`, and a fresh `ConfigVersionManager` snapshot store
    consumed by `main.on_config_change`.
    """
    from intellisource.config.loader import ConfigVersionManager
    from intellisource.observability.health import HealthChecker
    from intellisource.observability.metrics import MetricsCollector

    checker = HealthChecker()

    async def _check_db() -> bool:
        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def _check_redis() -> bool:
        try:
            await redis_client.ping()
            return True
        except Exception:
            return False

    async def _check_celery() -> bool:
        celery_app = getattr(app.state, "celery_app", None)
        if celery_app is None:
            return False
        try:
            # `control.ping` round-trips to a worker; treat any non-empty
            # response as healthy. Default timeout is short to avoid blocking
            # the /health endpoint on a stuck broker.
            replies = celery_app.control.ping(timeout=0.5)
            return bool(replies)
        except Exception:
            return False

    checker.register_check("db", _check_db)
    checker.register_check("redis", _check_redis)
    checker.register_check("celery", _check_celery)
    app.state.health_checker = checker

    app.state.metrics_collector = MetricsCollector.get_instance()
    app.state.config_version_manager = ConfigVersionManager()


def _install_webhook_state(app: FastAPI, *, redis_client: Any) -> None:
    """Wire webhook tokens + CS messenger clients onto `app.state`.

    Env presence rules:

    - `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` — when missing,
      the corresponding token state is set to "" and the router's signature
      check rejects every callback with 403 (no silent bypass). A startup
      warning is logged so operators notice the gap.
    - `IS_WECHAT_APP_ID` + `IS_WECHAT_APP_SECRET` — when **partially** set,
      `WeChatCustomerServiceClient.from_env` raises ValueError and that
      propagates out of `_install_webhook_state` to crash startup loud,
      matching the sprint-9 locked credential policy. When fully unset,
      construction is skipped and `wechat_cs_messenger` stays None.
    - `IS_WEWORK_CORP_ID` + `IS_WEWORK_CORP_SECRET` + `IS_WEWORK_AGENT_ID`
      follow the same partial-set hard-fail / fully-unset skip rule.
    """
    import logging

    from intellisource.distributor.wechat_cs_client import (
        WeChatCustomerServiceClient,
    )
    from intellisource.distributor.wework_cs_client import (
        WeWorkCustomerServiceClient,
    )

    logger = logging.getLogger(__name__)

    wechat_token = os.environ.get("IS_WECHAT_WEBHOOK_TOKEN", "")
    wework_token = os.environ.get("IS_WEWORK_WEBHOOK_TOKEN", "")
    app.state.wechat_webhook_token = wechat_token
    app.state.wework_webhook_token = wework_token

    http_client = _maybe_build_http_client()

    wechat_app_id_set = bool(os.environ.get("IS_WECHAT_APP_ID"))
    wechat_secret_set = bool(os.environ.get("IS_WECHAT_APP_SECRET"))
    if wechat_app_id_set or wechat_secret_set:
        # Partial-set → from_env raises and we let it propagate (hard fail).
        app.state.wechat_cs_messenger = WeChatCustomerServiceClient.from_env(
            redis_client=redis_client, http_client=http_client
        )
    else:
        app.state.wechat_cs_messenger = None

    wework_keys = (
        bool(os.environ.get("IS_WEWORK_CORP_ID")),
        bool(os.environ.get("IS_WEWORK_CORP_SECRET")),
        bool(os.environ.get("IS_WEWORK_AGENT_ID")),
    )
    if any(wework_keys):
        # Partial-set → from_env raises and we let it propagate (hard fail).
        app.state.wework_cs_messenger = WeWorkCustomerServiceClient.from_env(
            redis_client=redis_client, http_client=http_client
        )
    else:
        app.state.wework_cs_messenger = None

    if not wechat_token and not wework_token:
        logger.warning(
            "Both IS_WECHAT_WEBHOOK_TOKEN and IS_WEWORK_WEBHOOK_TOKEN are unset"
            " — /api/v1/webhooks/{wechat,wework} will reject all callbacks (403)"
        )


def _maybe_build_http_client() -> Any:
    """Return an `httpx.AsyncClient` instance, or `None` if httpx is unavailable."""
    try:
        import httpx

        return httpx.AsyncClient(timeout=10.0)
    except ImportError:
        return None


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
