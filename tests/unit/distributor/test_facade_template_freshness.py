"""P1 close-out: worker-side per-distribute template freshness.

A custom digest template created at runtime (via API / MCP / Agent) is persisted
to the DB and seen immediately by the API read path, but the worker render path
resolves templates from a process-local in-memory registry hydrated at boot — so
without this refresh a worker would render with a stale registry until it
restarts. ``DistributorFacade.distribute`` re-hydrates active DB templates into
the registry on every call, closing that cross-process gap.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.config.template_models import TemplateConfig
from intellisource.distributor.facade import DistributorFacade
from intellisource.distributor.matcher import SubscriptionMatcher
from intellisource.distributor.templates import TEMPLATE_REGISTRY
from intellisource.distributor.templates.db_template import DbDigestTemplate
from intellisource.storage.models import Base
from intellisource.template.service import TemplateService

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[Any]:
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _make() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    yield _make
    await eng.dispose()


def _facade(session_factory: Any) -> DistributorFacade:
    return DistributorFacade(
        session_factory=session_factory,
        matcher=SubscriptionMatcher(),
        channels={},
    )


@pytest.mark.asyncio
async def test_distribute_hydrates_runtime_db_template(session_factory: Any) -> None:
    """A template created after boot is renderable on the worker without restart."""
    name = "freshness-brief"
    TEMPLATE_REGISTRY.pop(name, None)
    try:
        # Persist a custom template *after* the facade is built (simulating a
        # runtime create on a worker whose registry was hydrated at boot).
        async with session_factory() as session:
            await TemplateService(session).create(
                TemplateConfig(
                    name=name,
                    base_template="daily-brief",
                    formats=["markdown"],
                    default_format="markdown",
                    jinja_source={"markdown": "# {{ bundle.title }}"},
                )
            )
            await session.commit()

        assert name not in TEMPLATE_REGISTRY, "precondition: not yet in registry"

        facade = _facade(session_factory)
        # content_id is a bad uuid → distribute early-returns content_not_found,
        # but hydration runs first, so the new template must now be resolvable.
        result = await facade.distribute(content_id="not-a-uuid")
        assert result["reason"] == "content_not_found"

        resolved = TEMPLATE_REGISTRY.get(name)
        assert isinstance(resolved, DbDigestTemplate)
        assert resolved.default_format == "markdown"
    finally:
        TEMPLATE_REGISTRY.pop(name, None)


@pytest.mark.asyncio
async def test_distribute_runs_hydration_before_work(session_factory: Any) -> None:
    """Hydration is the first thing distribute does — even on the early-return."""
    facade = _facade(session_factory)
    facade._hydrate_db_templates = AsyncMock()  # type: ignore[method-assign]
    await facade.distribute(content_id="not-a-uuid")
    facade._hydrate_db_templates.assert_awaited_once()


@pytest.mark.asyncio
async def test_hydration_is_best_effort_on_db_failure() -> None:
    """A templates-table error must never abort delivery."""

    @asynccontextmanager
    async def _boom() -> AsyncIterator[Any]:
        raise RuntimeError("templates table unreachable")
        yield  # pragma: no cover

    facade = _facade(_boom)
    # Must not raise despite the failing session factory.
    await facade._hydrate_db_templates()
