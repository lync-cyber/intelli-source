"""Small assembly helpers shared by the API and Worker compositions.

Each ``build_*`` here constructs one concrete dependency (LLM gateway,
collector registry, distributor facade, search-engine factory, pipeline
loader) with no knowledge of which process consumes it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from intellisource.collector.adapters.api import APICollector
from intellisource.collector.adapters.rss import RSSCollector
from intellisource.collector.adapters.web import WebCollector
from intellisource.collector.adaptive import AdaptiveScheduler
from intellisource.collector.proxy import ProxyManager
from intellisource.collector.rate_limiter import RateLimiter
from intellisource.collector.registry import CollectorRegistry
from intellisource.config.pipeline_models import PipelineConfig
from intellisource.core.errors import CompositionError
from intellisource.distributor.channels.email import EmailDistributor
from intellisource.distributor.channels.wechat import WeChatDistributor
from intellisource.distributor.channels.wework import WeWorkDistributor
from intellisource.distributor.facade import DistributorFacade
from intellisource.distributor.matcher import SubscriptionMatcher
from intellisource.llm.circuit_breaker import CircuitBreaker
from intellisource.llm.gateway import LLMGateway
from intellisource.observability.logging import get_logger
from intellisource.pipeline.definition_service import (
    PipelineDefinitionService,
    load_pipeline_config,
)
from intellisource.search.hybrid import HybridSearchEngine

_logger = get_logger(__name__)


def build_distributor_facade(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
    llm_gateway: LLMGateway | None = None,
) -> DistributorFacade:
    """Build a DistributorFacade; channels with missing env vars are soft-disabled.

    Each channel's ``from_env()`` is called independently.  When required
    credentials are absent a ``ValueError`` is caught, a WARNING is logged,
    and the channel is omitted from the facade rather than crashing startup.
    Subscriptions targeting a disabled channel are counted as *skipped* by
    ``DistributorFacade.distribute()``.

    When an ``llm_gateway`` is supplied the facade can optimize push copy
    before send (F-010, gated by ``IS_PUSH_OPTIMIZE_ENABLED``).
    """
    http_client = _build_http_client()
    channels: dict[str, Any] = {}

    builders: list[tuple[str, Callable[[], Any]]] = [
        (
            "wechat",
            lambda: WeChatDistributor.from_env(
                redis=redis_client, http_client=http_client
            ),
        ),
        (
            "wework",
            lambda: WeWorkDistributor.from_env(
                redis=redis_client, http_client=http_client
            ),
        ),
        ("email", EmailDistributor.from_env),
    ]
    for name, build_fn in builders:
        try:
            channels[name] = build_fn()
        except ValueError as exc:
            _logger.warning("distribution channel %r disabled: %s", name, exc)

    if not channels:
        _logger.warning(
            "no distribution channels configured — all push attempts will be skipped"
        )

    return DistributorFacade(
        session_factory=session_factory,
        matcher=SubscriptionMatcher(),
        channels=channels,
        llm_gateway=llm_gateway,
    )


def build_collector_registry(redis_client: Any | None = None) -> CollectorRegistry:
    """Register the three first-party collector adapters (RSS / API / Web)."""
    rate_limiter = RateLimiter(redis_client) if redis_client is not None else None
    proxy_cfg: dict[str, str] = {}
    proxy_manager = ProxyManager(proxy_cfg)
    adaptive = AdaptiveScheduler()
    registry = CollectorRegistry(
        rate_limiter=rate_limiter,
        proxy_manager=proxy_manager,
        adaptive=adaptive,
    )
    registry.register("rss", RSSCollector)
    registry.register("api", APICollector)
    registry.register("web", WebCollector)
    return registry


def build_llm_gateway(
    redis_client: Any,
    session_factory: Any | None = None,
) -> LLMGateway:
    """Assemble LLMGateway with its CircuitBreaker and optional
    session_factory.

    ``session_factory`` is the per-call DB session opener forwarded to
    ``LLMGateway`` so successful chat / complete / stream calls can persist
    ``llm_call_logs`` rows through a fresh ``CostTracker`` instance per call
    (B-042). When ``None`` (legacy unit tests / standalone gateway
    construction), the gateway runs without log_call persistence.
    """
    circuit_breaker = CircuitBreaker(redis=redis_client)
    return LLMGateway(
        circuit_breaker=circuit_breaker,
        session_factory=session_factory,
    )


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


def _run_coro_sync(coro: Any) -> Any:
    """Run *coro* to completion from a synchronous caller (e.g. a Celery task).

    Mirrors ``scheduler.tasks._run_sync``: uses a worker thread when an event
    loop is already running so the sync ``PipelineLoader.load`` is safe to call
    from either a plain worker process or (defensively) an async context.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class PipelineLoader:
    """Resolve a pipeline name to a `PipelineConfig`, database-first.

    The database is the system of record. When a name is absent from the DB
    (or the DB is unreachable), falls back to the YAML seed file so the worker
    can still resolve the shipped pipelines before/without a seed pass.

    Holds a stable, mockable dependency so `CeleryTasks.run_pipeline` can be
    injected with it instead of a free function.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def load(self, name: str) -> PipelineConfig:
        config: PipelineConfig | None = _run_coro_sync(self._load_from_db(name))
        if config is not None:
            return config
        return load_pipeline_config(name)

    async def _load_from_db(self, name: str) -> PipelineConfig | None:
        if self._session_factory is None:
            return None
        try:
            async with self._session_factory() as session:
                return await PipelineDefinitionService(session).load(name)
        except Exception as exc:  # noqa: BLE001 — fall back to YAML on any DB error
            _logger.warning(
                "DB pipeline load failed for %r; falling back to yaml seed: %s",
                name,
                exc,
            )
            return None


def build_pipeline_loader(session_factory: Any) -> PipelineLoader:
    return PipelineLoader(session_factory)


def _maybe_build_http_client() -> Any:
    """Return an `httpx.AsyncClient` instance, or `None` if httpx is unavailable."""
    try:
        import httpx

        return httpx.AsyncClient(timeout=10.0)
    except ImportError:
        return None


def _build_http_client() -> Any:
    """Return an async HTTP client for production channels, or fail loudly."""
    http_client = _maybe_build_http_client()
    if http_client is None:
        raise CompositionError("httpx is required to build distributor channels")
    return http_client
