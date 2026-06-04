"""P1-b: TemplateService — DB-backed CRUD over a real (SQLite) session."""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from intellisource.config.template_models import (
    TemplateConfig,
    TemplateValidationError,
)
from intellisource.storage.models import Base
from intellisource.template.service import TemplateService

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


def _cfg(name: str = "my", **overrides: Any) -> TemplateConfig:
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
async def test_create_and_get_by_name(session: AsyncSession) -> None:
    svc = TemplateService(session)
    created = await svc.create(_cfg())
    await session.commit()

    assert created.name == "my"
    assert created.base_template == "daily-brief"

    fetched = await svc.get_by_name("my")
    assert fetched is not None
    assert fetched.formats == ["markdown"]
    assert fetched.jinja_source == {"markdown": "# {{ bundle.title }}"}
    assert fetched.status == "active"


@pytest.mark.asyncio
async def test_create_is_idempotent_upsert_by_name(session: AsyncSession) -> None:
    svc = TemplateService(session)
    await svc.create(_cfg())
    await session.commit()
    await svc.create(
        _cfg(
            formats=["markdown", "text"],
            jinja_source={"markdown": "a", "text": "b"},
        )
    )
    await session.commit()

    active = await svc.list_active()
    assert [r.name for r in active] == ["my"]
    fetched = await svc.get_by_name("my")
    assert fetched is not None
    assert set(fetched.formats) == {"markdown", "text"}


@pytest.mark.asyncio
async def test_create_rejects_unknown_base_template(session: AsyncSession) -> None:
    svc = TemplateService(session)
    with pytest.raises(TemplateValidationError):
        await svc.create(_cfg(base_template="not-a-real-base"))


@pytest.mark.asyncio
async def test_get_by_id_and_patch(session: AsyncSession) -> None:
    svc = TemplateService(session)
    created = await svc.create(_cfg())
    await session.commit()

    got = await svc.get(created.id)
    assert got is not None
    assert got.id == created.id

    patched = await svc.patch(
        created.id, {"jinja_source": {"markdown": "NEW {{ bundle.title }}"}}
    )
    assert patched is not None
    assert patched.jinja_source == {"markdown": "NEW {{ bundle.title }}"}


@pytest.mark.asyncio
async def test_patch_rejects_unknown_base_template(session: AsyncSession) -> None:
    svc = TemplateService(session)
    created = await svc.create(_cfg())
    await session.commit()
    with pytest.raises(TemplateValidationError):
        await svc.patch(created.id, {"base_template": "ghost"})


@pytest.mark.asyncio
async def test_patch_unknown_id_returns_none(session: AsyncSession) -> None:
    svc = TemplateService(session)
    result = await svc.patch(uuid.uuid4(), {"status": "archived"})
    assert result is None


@pytest.mark.asyncio
async def test_delete(session: AsyncSession) -> None:
    svc = TemplateService(session)
    created = await svc.create(_cfg())
    await session.commit()

    assert await svc.delete(created.id) is True
    assert await svc.get(created.id) is None
    # second delete is a no-op
    assert await svc.delete(created.id) is False


@pytest.mark.asyncio
async def test_list_paginated_and_active_filter(session: AsyncSession) -> None:
    svc = TemplateService(session)
    await svc.create(_cfg(name="a"))
    await svc.create(_cfg(name="b", status="archived"))
    await session.commit()

    page = await svc.list_paginated(limit=10)
    assert {r.name for r in page["items"]} >= {"a", "b"}
    assert page["has_more"] is False

    active = await svc.list_active()
    assert {r.name for r in active} == {"a"}
