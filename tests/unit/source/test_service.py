"""RED tests for SourceConfigService (B-058a + B-058b).

Tests import from ``intellisource.source.service`` which does NOT YET EXIST;
all tests are expected to FAIL during the TDD RED phase.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Text, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.models import SourceConfig

# ---------------------------------------------------------------------------
# Import the not-yet-existing service (will ImportError → RED)
# ---------------------------------------------------------------------------
from intellisource.source.service import SourceConfigService  # type: ignore[import]
from intellisource.storage.models import Base, Source

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _remove_pg_only_indexes(base: type[Base]) -> None:
    for table in base.metadata.tables.values():
        to_remove = []
        for idx in table.indexes:
            opts = getattr(idx, "dialect_options", {}).get("postgresql", {})
            if opts.get("using") or opts.get("ops"):
                to_remove.append(idx)
        for idx in to_remove:
            table.indexes.discard(idx)


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
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS config_versions ("
            " id TEXT PRIMARY KEY,"
            " version TEXT NOT NULL UNIQUE,"
            " snapshot_yaml TEXT NOT NULL,"
            " author TEXT,"
            " created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
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


def _cfg(name: str, type_: str = "rss", url: str | None = None) -> SourceConfig:
    return SourceConfig(
        name=name,
        type=type_,  # type: ignore[arg-type]
        url=url or f"https://example.com/{name}.rss",
        tags=["x"],
    )


# ---------------------------------------------------------------------------
# TestSourceConfigServiceListPaginated
# ---------------------------------------------------------------------------


class TestSourceConfigServiceListPaginated:
    async def test_list_paginated_empty_returns_empty_items(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        result = await svc.list_paginated()
        assert result["items"] == [], "list_paginated on empty DB must return items=[]"
        assert result["next_cursor"] is None
        assert result["has_more"] is False

    async def test_list_paginated_returns_existing_sources(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        await svc.create(_cfg("src-a"))
        await svc.create(_cfg("src-b"))
        result = await svc.list_paginated()
        assert len(result["items"]) == 2, (
            "list_paginated must return both created sources; "
            f"got {len(result['items'])} items"
        )


# ---------------------------------------------------------------------------
# TestSourceConfigServiceCreate
# ---------------------------------------------------------------------------


class TestSourceConfigServiceCreate:
    async def test_create_persists_source_with_all_fields(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        cfg = _cfg("news-src", type_="rss", url="https://example.com/news.rss")
        await svc.create(cfg)
        rows = (await session.execute(select(Source))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.name == "news-src"
        assert row.type == "rss"
        assert row.url == "https://example.com/news.rss"
        assert row.tags == ["x"]
        assert row.status == "active"


# ---------------------------------------------------------------------------
# TestSourceConfigServicePatch
# ---------------------------------------------------------------------------


class TestSourceConfigServicePatch:
    async def test_patch_updates_specified_fields_only(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        created = await svc.create(
            _cfg("patch-src", url="https://example.com/orig.rss")
        )
        patched = await svc.patch(created.id, {"url": "https://example.com/new.rss"})
        assert patched is not None
        assert patched.url == "https://example.com/new.rss", (
            "patch must update the url field to the new value"
        )
        assert patched.name == "patch-src", (
            "patch must not change fields that were not specified"
        )

    async def test_patch_returns_none_for_unknown_id(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        result = await svc.patch(uuid.uuid4(), {"url": "https://example.com/x.rss"})
        assert result is None, "patch on a non-existent source id must return None"


# ---------------------------------------------------------------------------
# TestSourceConfigServiceDelete
# ---------------------------------------------------------------------------


class TestSourceConfigServiceDelete:
    async def test_delete_soft_marks_status_paused(self, session: AsyncSession) -> None:
        svc = SourceConfigService(session)
        created = await svc.create(_cfg("del-src"))
        ok = await svc.delete(created.id)
        assert ok is True
        rows = (await session.execute(select(Source))).scalars().all()
        assert len(rows) == 1, "soft delete must not remove the row from DB"
        assert rows[0].status == "paused", (
            f"soft delete must set status='paused'; got status='{rows[0].status}'"
        )

    async def test_delete_returns_false_for_unknown_id(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        result = await svc.delete(uuid.uuid4())
        assert result is False, "delete for a non-existent id must return False"


# ---------------------------------------------------------------------------
# TestSourceConfigServiceBulkSyncWithVersion  (B-058a core coverage)
# ---------------------------------------------------------------------------


class TestSourceConfigServiceBulkSyncWithVersion:
    async def test_bulk_sync_writes_version_snapshot_to_config_versions_table(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")], author="test")
        row = (
            await session.execute(
                text("SELECT version, author, snapshot_yaml FROM config_versions")
            )
        ).fetchone()
        assert row is not None, (
            "bulk_sync_with_version must write a row to config_versions table"
        )
        assert row[0] != "", "version must be a non-empty string"
        assert row[1] == "test", f"author must be 'test', got '{row[1]}'"
        import yaml

        parsed = yaml.safe_load(row[2])
        names = {item["name"] for item in parsed}
        assert names == {"a", "b"}, (
            f"snapshot_yaml must contain both config names; got names={names}"
        )

    async def test_bulk_sync_returns_loaded_count_and_version(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        result = await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])
        assert "loaded_count" in result, "result must have 'loaded_count' key"
        assert "version" in result, "result must have 'version' key"
        assert "errors" in result, "result must have 'errors' key"
        assert result["loaded_count"] == 2, (
            f"loaded_count must be 2 for 2 valid configs; got {result['loaded_count']}"
        )
        assert result["errors"] == [], (
            f"errors must be empty for all-valid configs; got {result['errors']}"
        )
        assert result["version"] != "", "version must be a non-empty string"

    async def test_bulk_sync_skips_invalid_configs_and_appends_errors(
        self, session: AsyncSession
    ) -> None:
        from unittest.mock import patch

        svc = SourceConfigService(session)
        valid_cfg = _cfg("valid-src")
        # Patch SourceConfig url_must_be_valid to let a bad cfg through pydantic
        # then patch the service's internal validator to simulate failure on second item
        bad_cfg = _cfg("bad-src")

        call_count = 0

        def _fake_validate(cfg: SourceConfig) -> SourceConfig:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("simulated validation failure for bad-src")
            return cfg

        # SourceConfigService must call a validate step; patch it
        with patch.object(
            svc, "_validate_config", side_effect=_fake_validate, create=True
        ):
            result = await svc.bulk_sync_with_version([valid_cfg, bad_cfg])

        assert result["loaded_count"] == 1, (
            f"loaded_count must be 1 (one config passed); got {result['loaded_count']}"
        )
        assert len(result["errors"]) == 1, (
            f"errors must have 1 entry for the bad config; got {result['errors']}"
        )

    async def test_bulk_sync_upserts_sources_to_db(self, session: AsyncSession) -> None:
        svc = SourceConfigService(session)
        await svc.bulk_sync_with_version([_cfg("src-x"), _cfg("src-y")])
        rows = (await session.execute(select(Source))).scalars().all()
        names = {r.name for r in rows}
        assert names == {"src-x", "src-y"}, (
            f"bulk_sync must upsert sources to DB; found names={names}"
        )

    async def test_bulk_sync_with_no_configs_records_empty_version(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        result = await svc.bulk_sync_with_version([])
        assert result["loaded_count"] == 0
        assert result["version"] != "", (
            "even an empty sync must record a version snapshot"
        )
        row = (
            await session.execute(text("SELECT version FROM config_versions"))
        ).fetchone()
        assert row is not None, (
            "empty bulk_sync_with_version must still write a row to config_versions"
        )
        assert row[0] != "", "recorded version must be a non-empty string"


# ---------------------------------------------------------------------------
# TestSourceConfigServiceRollbackToVersion  (B-058b real bug coverage)
# ---------------------------------------------------------------------------


class TestSourceConfigServiceRollbackToVersion:
    async def test_rollback_restores_db_rows_to_snapshot_state(
        self, session: AsyncSession
    ) -> None:
        """Core B-058b RED assertion: rollback must write back to DB.

        Current router implementation (routers/sources.py:224-249) only calls
        rollback_by_label then returns — it never calls bulk_sync_from_configs.
        The SourceConfigService.rollback_to_version implementation must do both.
        """
        svc = SourceConfigService(session)
        # Step 1: sync two configs to establish v1
        original_url_a = "https://example.com/src-a.rss"
        await svc.bulk_sync_with_version(
            [
                _cfg("src-a", url=original_url_a),
                _cfg("src-b"),
            ]
        )
        # Step 2: mutate src-a url and soft-delete src-b
        rows = (await session.execute(select(Source))).scalars().all()
        by_name = {r.name: r for r in rows}
        by_name["src-a"].url = "https://example.com/mutated.rss"
        by_name["src-b"].status = "paused"
        await session.flush()

        # Verify mutation took effect
        mutated = (
            await session.execute(select(Source).where(Source.name == "src-a"))
        ).scalar_one()
        assert mutated.url == "https://example.com/mutated.rss"

        # Step 3: rollback to version "1"
        result = await svc.rollback_to_version("1")

        # Step 4: assert DB reflects the v1 snapshot
        after_a = (
            await session.execute(select(Source).where(Source.name == "src-a"))
        ).scalar_one()
        assert after_a.url == original_url_a, (
            f"rollback to v1 must restore src-a.url to '{original_url_a}'; "
            f"got '{after_a.url}'. This is the B-058b real bug: "
            "the router currently returns the snapshot without writing to DB."
        )

        after_b = (
            await session.execute(select(Source).where(Source.name == "src-b"))
        ).scalar_one_or_none()
        assert after_b is not None, "rollback to v1 must restore src-b row"
        assert after_b.status == "active", (
            f"rollback to v1 must reactivate src-b; got status='{after_b.status}'"
        )
        assert result["rolled_back_to"] == "1"

    async def test_rollback_returns_summary_dict(self, session: AsyncSession) -> None:
        svc = SourceConfigService(session)
        await svc.bulk_sync_with_version([_cfg("src-r1"), _cfg("src-r2")])

        fresh = SourceConfigService(session)
        result = await fresh.rollback_to_version("1")

        assert "rolled_back_to" in result, "result must contain 'rolled_back_to' key"
        assert "config_count" in result, "result must contain 'config_count' key"
        assert "source_names" in result, "result must contain 'source_names' key"
        assert result["rolled_back_to"] == "1", (
            f"rolled_back_to must be '1'; got '{result['rolled_back_to']}'"
        )
        assert result["config_count"] == 2, (
            f"config_count must be 2; got {result['config_count']}"
        )
        assert sorted(result["source_names"]) == ["src-r1", "src-r2"], (
            f"source_names must list both configs; got {result['source_names']}"
        )

    async def test_rollback_raises_valueerror_for_unknown_version(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        with pytest.raises(ValueError, match="not found"):
            await svc.rollback_to_version("99")

    async def test_rollback_to_empty_snapshot_pauses_all_existing_sources(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        # Record an empty snapshot as v1
        await svc.bulk_sync_with_version([])
        v1_label = "1"
        # Add a source after v1 was recorded
        await svc.create(_cfg("late-src"))
        rows_before = (await session.execute(select(Source))).scalars().all()
        assert any(r.name == "late-src" for r in rows_before), (
            "late-src must exist before rollback"
        )
        # Rollback to the empty v1 snapshot → late-src should be paused
        await svc.rollback_to_version(v1_label)
        late = (
            await session.execute(select(Source).where(Source.name == "late-src"))
        ).scalar_one_or_none()
        assert late is not None, "soft-rollback must not hard-delete late-src"
        assert late.status == "paused", (
            f"rollback to empty snapshot must set late-src status='paused'; "
            f"got '{late.status}'"
        )


# ---------------------------------------------------------------------------
# get / list_versions / diff_with_yaml
# ---------------------------------------------------------------------------


class TestSourceGet:
    async def test_get_returns_source_by_id(self, session: AsyncSession) -> None:
        svc = SourceConfigService(session)
        created = await svc.create(_cfg("g"))
        fetched = await svc.get(created.id)
        assert fetched is not None
        assert fetched.name == "g"

    async def test_get_missing_id_returns_none(self, session: AsyncSession) -> None:
        svc = SourceConfigService(session)
        assert await svc.get(uuid.uuid4()) is None


class TestSourceListVersions:
    async def test_list_versions_newest_first_with_count(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        await svc.bulk_sync_with_version([_cfg("a")])  # v1, 1 config
        await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])  # v2, 2 configs

        versions = await svc.list_versions(limit=10)
        assert [v["version"] for v in versions] == ["2", "1"]
        assert versions[0]["config_count"] == 2
        assert versions[1]["config_count"] == 1


class TestSourceDiffWithYaml:
    async def test_diff_partitions_names_and_marks_preserve(
        self, session: AsyncSession
    ) -> None:
        svc = SourceConfigService(session)
        await svc.create(_cfg("keep"))
        await svc.create(_cfg("gone"))

        diff = await svc.diff_with_yaml([_cfg("keep"), _cfg("fresh")])
        assert diff["yaml_only"] == ["fresh"]
        assert diff["db_only"] == ["gone"]
        assert diff["both"] == ["keep"]
        # sources reload is additive (bulk_upsert) → db-only rows survive.
        assert diff["db_only_action"] == "preserve"
