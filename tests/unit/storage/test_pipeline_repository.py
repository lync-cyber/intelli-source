"""Tests for PipelineRepository: definition header + ordered steps persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.pipeline_models import PipelineConfig
from intellisource.storage.models import Base, PipelineStep
from intellisource.storage.repositories.pipeline import PipelineRepository

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base) -> None:
    for table in base.metadata.tables.values():
        to_remove = []
        for idx in table.indexes:
            pg_opts = getattr(idx, "dialect_options", {}).get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                to_remove.append(idx)
        for idx in to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest.fixture
async def engine():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    _remove_pg_only_indexes(Base)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as sess:
        yield sess


def _flexible_config(name: str = "instant-search") -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "max_steps": 12,
            "on_failure": "skip",
            "agent_mode": "process",
            "system_prompt": "你是搜索助手",
            "max_tokens_budget": 4096,
            "tools_allowed": ["search", "get_content_detail"],
            "tools_denied": ["collect", "distribute"],
            "tool_permissions": {"distribute": "deny"},
            "steps": [
                {"tool": "search", "params": {"top_k": 5}},
                {"tool": "summarize_for_user", "params": {}},
            ],
        }
    )


class TestPipelineRepositoryUpsert:
    async def test_upsert_creates_header_and_ordered_steps(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        created = await repo.upsert(_flexible_config("manual-collect"))

        assert created.name == "manual-collect"
        assert created.mode == "flexible"
        assert created.max_steps == 12
        assert created.on_failure == "skip"
        assert created.agent_mode == "process"
        assert created.system_prompt == "你是搜索助手"
        assert created.max_tokens_budget == 4096
        assert created.tools_allowed == ["search", "get_content_detail"]
        assert created.tools_denied == ["collect", "distribute"]
        assert created.tool_permissions == {"distribute": "deny"}
        assert created.status == "active"

        fetched = await repo.get_by_name("manual-collect")
        assert fetched is not None
        positions = [s.position for s in fetched.steps]
        assert positions == [0, 1]
        assert fetched.steps[0].definition == {"tool": "search", "params": {"top_k": 5}}
        assert fetched.steps[1].definition == {
            "tool": "summarize_for_user",
            "params": {},
        }

    async def test_upsert_existing_name_replaces_steps_not_duplicates(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        await repo.upsert(_flexible_config("p1"))

        updated_cfg = PipelineConfig.from_dict(
            {
                "name": "p1",
                "mode": "strict",
                "max_steps": 3,
                "on_failure": "abort",
                "steps": [{"tool": "collect", "params": {}}],
            }
        )
        updated = await repo.upsert(updated_cfg)

        assert updated.mode == "strict"
        assert updated.max_steps == 3
        fetched = await repo.get_by_name("p1")
        assert fetched is not None
        assert len(fetched.steps) == 1
        assert fetched.steps[0].definition == {"tool": "collect", "params": {}}

        # No orphaned steps left behind across the whole table.
        all_steps = (await session.execute(_select_all_steps())).scalars().all()
        assert len(list(all_steps)) == 1


class TestPipelineRepositoryRead:
    async def test_get_by_name_absent_returns_none(self, session: AsyncSession) -> None:
        repo = PipelineRepository(session)
        assert await repo.get_by_name("nope") is None

    async def test_list_filters_status_and_paginates(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        await repo.upsert(_flexible_config("a"))
        await repo.upsert(_flexible_config("b"))
        archived = _flexible_config("c")
        created = await repo.upsert(archived)
        created.status = "archived"
        await session.flush()

        page = await repo.list_paginated(status="active", limit=20)
        names = {p.name for p in page["items"]}
        assert names == {"a", "b"}
        assert page["has_more"] is False

    async def test_list_names_returns_all(self, session: AsyncSession) -> None:
        repo = PipelineRepository(session)
        await repo.upsert(_flexible_config("a"))
        await repo.upsert(_flexible_config("b"))
        assert sorted(await repo.list_names()) == ["a", "b"]

    async def test_list_all_returns_every_pipeline_with_steps(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        await repo.upsert(_flexible_config("z"))
        await repo.upsert(_flexible_config("a"))
        rows = await repo.list_all()
        assert [p.name for p in rows] == ["a", "z"]
        assert len(rows[0].steps) == 2


class TestPipelineRepositoryDelete:
    async def test_delete_by_name_removes_header_and_steps(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        await repo.upsert(_flexible_config("doomed"))

        assert await repo.delete_by_name("doomed") is True
        assert await repo.get_by_name("doomed") is None
        remaining = (await session.execute(_select_all_steps())).scalars().all()
        assert list(remaining) == []

    async def test_delete_by_name_absent_returns_false(
        self, session: AsyncSession
    ) -> None:
        repo = PipelineRepository(session)
        assert await repo.delete_by_name("ghost") is False


def _select_all_steps():
    from sqlalchemy import select

    return select(PipelineStep)
