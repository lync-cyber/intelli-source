"""Tests for PipelineDefinitionService: DB-backed pipeline definitions + YAML seed."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.pipeline_models import PipelineConfig
from intellisource.pipeline.definition_service import PipelineDefinitionService
from intellisource.storage.models import Base

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest.fixture
async def session():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


def _config(name: str = "instant-search") -> PipelineConfig:
    return PipelineConfig.from_dict(
        {
            "name": name,
            "mode": "flexible",
            "max_steps": 5,
            "on_failure": "skip",
            "tools_allowed": ["search", "summarize_for_user"],
            "tools_denied": ["collect"],
            "tool_permissions": {"collect": "deny"},
            "steps": [
                {"tool": "search", "params": {"query": ""}},
                {"tool": "summarize_for_user", "params": {}},
            ],
        }
    )


class TestCreateAndRead:
    async def test_create_then_get_roundtrip_preserves_all_fields(
        self, session: AsyncSession
    ) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("manual-collect"))

        loaded = await svc.get("manual-collect")
        assert loaded is not None
        assert loaded.name == "manual-collect"
        assert loaded.mode == "flexible"
        assert loaded.max_steps == 5
        assert loaded.on_failure == "skip"
        assert loaded.tools_allowed == ["search", "summarize_for_user"]
        assert loaded.tools_denied == ["collect"]
        assert loaded.tool_permissions == {"collect": "deny"}
        assert loaded.steps == [
            {"tool": "search", "params": {"query": ""}},
            {"tool": "summarize_for_user", "params": {}},
        ]

    async def test_get_absent_returns_none(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        assert await svc.get("missing") is None

    async def test_load_is_db_first_and_none_when_absent(
        self, session: AsyncSession
    ) -> None:
        svc = PipelineDefinitionService(session)
        assert await svc.load("missing") is None
        await svc.create(_config("present"))
        loaded = await svc.load("present")
        assert loaded is not None
        assert loaded.name == "present"

    async def test_create_update_replaces_definition(
        self, session: AsyncSession
    ) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("p"))
        await svc.create(
            PipelineConfig.from_dict(
                {
                    "name": "p",
                    "mode": "strict",
                    "max_steps": 2,
                    "on_failure": "abort",
                    "steps": [{"tool": "collect", "params": {}}],
                }
            )
        )
        loaded = await svc.get("p")
        assert loaded is not None
        assert loaded.mode == "strict"
        assert loaded.steps == [{"tool": "collect", "params": {}}]

    async def test_list_summaries(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("a"))
        await svc.create(_config("b"))
        summaries = await svc.list_summaries()
        names = {s["name"] for s in summaries}
        assert names == {"a", "b"}
        assert all("mode" in s and "max_steps" in s for s in summaries)


class TestUpdate:
    async def test_update_merges_partial_fields_and_persists(
        self, session: AsyncSession
    ) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("p"))  # mode=flexible, max_steps=5

        updated = await svc.update("p", {"max_steps": 9})
        assert updated is not None
        assert updated.max_steps == 9
        assert updated.mode == "flexible"  # untouched field preserved

        reloaded = await svc.get("p")
        assert reloaded is not None
        assert reloaded.max_steps == 9
        assert reloaded.tools_allowed == ["search", "summarize_for_user"]

    async def test_update_absent_returns_none(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        assert await svc.update("ghost", {"max_steps": 1}) is None

    async def test_update_rejects_invalid_mode(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("p"))
        with pytest.raises(ValueError):
            await svc.update("p", {"mode": "bogus"})

    async def test_update_ignores_name_field(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("p"))
        updated = await svc.update("p", {"name": "renamed", "max_steps": 7})
        assert updated is not None
        assert updated.name == "p"  # the path key wins; name is immutable
        assert updated.max_steps == 7


class TestDelete:
    async def test_delete_existing(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        await svc.create(_config("doomed"))
        assert await svc.delete("doomed") is True
        assert await svc.get("doomed") is None

    async def test_delete_absent_returns_false(self, session: AsyncSession) -> None:
        svc = PipelineDefinitionService(session)
        assert await svc.delete("ghost") is False


class TestSeedFromYaml:
    async def test_seed_imports_then_idempotent(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        (tmp_path / "one.yaml").write_text(
            "name: one\nmode: strict\non_failure: abort\nmax_steps: 3\n"
            "steps:\n  - tool: collect\n    params: {}\n",
            encoding="utf-8",
        )
        (tmp_path / "two.yaml").write_text(
            "name: two\nmode: flexible\non_failure: skip\nmax_steps: 4\n"
            "tools_allowed: [search]\nsteps:\n  - tool: search\n    params: {}\n",
            encoding="utf-8",
        )
        svc = PipelineDefinitionService(session, yaml_dir=tmp_path)

        created = await svc.seed_from_yaml()
        assert created == 2
        assert sorted(s["name"] for s in await svc.list_summaries()) == ["one", "two"]

        # Idempotent: a second seed creates nothing.
        assert await svc.seed_from_yaml() == 0

    async def test_seed_does_not_overwrite_db_edits(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        (tmp_path / "one.yaml").write_text(
            "name: one\nmode: strict\non_failure: abort\nmax_steps: 3\n"
            "steps:\n  - tool: collect\n    params: {}\n",
            encoding="utf-8",
        )
        svc = PipelineDefinitionService(session, yaml_dir=tmp_path)
        await svc.seed_from_yaml()
        # Edit via the service (DB now authoritative).
        await svc.create(
            PipelineConfig.from_dict(
                {
                    "name": "one",
                    "mode": "flexible",
                    "on_failure": "skip",
                    "max_steps": 9,
                    "steps": [{"tool": "search", "params": {}}],
                }
            )
        )
        await svc.seed_from_yaml()  # must not clobber the DB edit
        loaded = await svc.get("one")
        assert loaded is not None
        assert loaded.mode == "flexible"
        assert loaded.max_steps == 9
