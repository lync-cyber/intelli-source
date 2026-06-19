"""Worker-side composition entry point.

``build_worker_composition`` is called from
``scheduler/boot.py:worker_init_handler`` on Celery worker process init and
returns the ``WorkerComposition`` bundle the handler feeds into
``build_celery_tasks``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from intellisource.agent.runner import AgentRunner
from intellisource.collector.registry import CollectorRegistry
from intellisource.composition.builders import PipelineLoader, build_pipeline_loader
from intellisource.composition.deps import _build_deps_bundle, _install_agent_runner
from intellisource.distributor.facade import DistributorFacade
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)


@dataclass
class WorkerComposition:
    """Bundle of dependencies returned by `build_worker_composition`."""

    agent_runner: AgentRunner
    pipeline_loader: PipelineLoader
    collector_registry: CollectorRegistry
    distributor: DistributorFacade
    session_factory: async_sessionmaker[AsyncSession]


def hydrate_worker_template_registry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Best-effort load of active custom templates into the digest registry.

    Called from worker boot. Lives in the composition root (a layer above
    ``distributor``) so the ``scheduler`` boot hook never needs a direct edge to
    ``distributor`` — keeping the sibling-independence contract intact. Failures
    (e.g. a not-yet-migrated DB) are logged and swallowed so the worker boots.
    """
    from intellisource.template.service import hydrate_template_registry

    async def _run() -> int:
        async with session_factory() as session:
            return await hydrate_template_registry(session)

    coro = _run()
    try:
        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(coro)
        finally:
            loop.close()
        if count:
            _logger.info("hydrated %d custom template(s) into the registry", count)
    except Exception as exc:
        coro.close()
        _logger.warning("template registry hydration skipped: %s", exc)


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

    Wires ``llm_gateway`` into the DistributorFacade so the Worker path
    (which runs distribute under ``run_pipeline``) can optimize push copy
    before send when ``IS_PUSH_OPTIMIZE_ENABLED=1`` (F-010).
    """
    from intellisource.scheduler.celery_app import (
        celery_app as _worker_celery_app,
    )

    bundle = _build_deps_bundle(
        session_factory, redis_client, celery_app=_worker_celery_app
    )
    agent_runner = _install_agent_runner(session_factory, bundle)
    pipeline_loader = build_pipeline_loader(session_factory)

    # Wire the periodic-digest runner onto the shared Celery app so the
    # ``assemble_daily_weekly_digests`` beat task can reach it. It reuses the
    # facade's channels and the LLM gateway (for opt-in digest enrichment).
    from intellisource.distributor.periodic import PeriodicDigestRunner

    setattr(
        _worker_celery_app,
        "_periodic_digest_runner",
        PeriodicDigestRunner(
            session_factory=session_factory,
            channels=bundle.distributor.channels,
            llm_gateway=bundle.llm_gateway,
        ),
    )

    # Wire the session factory the ``cleanup_chat_sessions`` beat task uses to
    # purge chat sessions inactive past the IS_CHAT_SESSION_TTL_DAYS TTL.
    setattr(_worker_celery_app, "_chat_session_cleanup_factory", session_factory)

    return WorkerComposition(
        agent_runner=agent_runner,
        pipeline_loader=pipeline_loader,
        collector_registry=bundle.collector_registry,
        distributor=bundle.distributor,
        session_factory=session_factory,
    )
