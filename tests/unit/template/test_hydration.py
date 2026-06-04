"""P1-b: startup hydration of DB templates into the digest registry."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.config.template_models import TemplateConfig
from intellisource.distributor.templates import TEMPLATE_REGISTRY, get_template
from intellisource.distributor.templates.db_template import DbDigestTemplate
from intellisource.storage.models import Base
from intellisource.template.service import TemplateService, hydrate_template_registry

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    db = factory()
    yield db
    await db.close()
    await eng.dispose()


def _cfg(name: str, **overrides: Any) -> TemplateConfig:
    payload: dict[str, Any] = {
        "name": name,
        "base_template": "daily-brief",
        "formats": ["markdown"],
        "default_format": "markdown",
        "jinja_source": {"markdown": "# {{ bundle.title }}"},
    }
    payload.update(overrides)
    return TemplateConfig(**payload)


@pytest.mark.asyncio
async def test_hydrate_registers_only_active_templates(session: AsyncSession) -> None:
    svc = TemplateService(session)
    await svc.create(_cfg("hydrate-active"))
    await svc.create(_cfg("hydrate-archived", status="archived"))
    await session.commit()

    try:
        count = await hydrate_template_registry(session)
        assert count == 1
        resolved = get_template("hydrate-active")
        assert isinstance(resolved, DbDigestTemplate)
        assert "hydrate-archived" not in TEMPLATE_REGISTRY
    finally:
        TEMPLATE_REGISTRY.pop("hydrate-active", None)
        TEMPLATE_REGISTRY.pop("hydrate-archived", None)


def test_worker_hydrate_is_best_effort_on_failure() -> None:
    from intellisource.composition import hydrate_worker_template_registry

    def _bad_factory() -> Any:
        raise RuntimeError("db unreachable")

    # must swallow the error so worker boot is never aborted by hydration
    hydrate_worker_template_registry(_bad_factory)  # type: ignore[arg-type]
