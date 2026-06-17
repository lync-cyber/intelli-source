"""Tests for SubscriptionService — service layer (Layer 2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidationError
from intellisource.storage.models import Base, Subscription
from intellisource.subscription.service import SubscriptionService

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
        # subscription_config_versions table for record_version_async
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS subscription_config_versions ("
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


def _cfg(name: str, channel: str = "wework") -> SubscriptionConfig:
    if channel == "wework":
        return SubscriptionConfig(
            name=name,
            channel="wework",
            channel_config={"user_id": "@all", "msg_type": "text"},
            match_rules={"tags": ["x"]},
        )
    if channel == "email":
        return SubscriptionConfig(
            name=name,
            channel="email",
            channel_config={"to_addr": "u@x.com"},
            match_rules={"tags": ["x"]},
        )
    return SubscriptionConfig(name=name, channel="wechat", match_rules={"tags": ["x"]})


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_persists_subscription(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        created = await svc.create(_cfg("alpha"))
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert len(rows) == 1
        assert created.name == "alpha"
        assert rows[0].channel_config["user_id"] == "@all"

    async def test_create_runs_validator_and_rejects_bad_config(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        bad = SubscriptionConfig(
            name="bad-email",
            channel="email",
            channel_config={},  # missing to_addr — validator should reject
            match_rules={},
        )
        with pytest.raises(SubscriptionValidationError, match="to_addr"):
            await svc.create(bad)
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert rows == [], "validator failure must not persist anything"


# ---------------------------------------------------------------------------
# patch / delete
# ---------------------------------------------------------------------------


class TestPatchAndDelete:
    async def test_patch_partial_update(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        created = await svc.create(_cfg("p"))
        patched = await svc.patch(created.id, {"frequency": "daily"})
        assert patched is not None
        assert patched.frequency == "daily"

    async def test_patch_returns_none_when_id_missing(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        result = await svc.patch(uuid.uuid4(), {"frequency": "daily"})
        assert result is None

    async def test_delete_is_soft_paused(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        created = await svc.create(_cfg("d"))
        ok = await svc.delete(created.id)
        assert ok is True
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert len(rows) == 1, "soft delete must not remove the row"
        assert rows[0].status == "paused"

    async def test_delete_missing_id_returns_false(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        assert await svc.delete(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# bulk_sync_with_version
# ---------------------------------------------------------------------------


class TestBulkSyncWithVersion:
    async def test_bulk_sync_records_version_label(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        result = await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])
        assert result["loaded_count"] == 2
        assert result["version"] == "1"
        assert result["errors"] == []

    async def test_bulk_sync_writes_snapshot_to_db(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        await svc.bulk_sync_with_version([_cfg("a")])
        # row landed in subscription_config_versions
        row = (
            await session.execute(
                select(  # type: ignore[arg-type]
                    Subscription
                ).where(Subscription.name == "a")
            )
        ).scalar_one_or_none()
        assert row is not None, "bulk_sync_with_version must persist the synced row"
        assert row.name == "a"

    async def test_bulk_sync_per_config_validation_failure_is_skipped(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        bad_email = SubscriptionConfig(
            name="bad",
            channel="email",
            channel_config={},
            match_rules={},
        )
        result = await svc.bulk_sync_with_version([_cfg("ok"), bad_email])
        assert result["loaded_count"] == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["name"] == "bad"

    async def test_bulk_sync_soft_deletes_absent(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])
        await svc.bulk_sync_with_version([_cfg("a")])
        rows = (await session.execute(select(Subscription))).scalars().all()
        by_name = {r.name: r for r in rows}
        assert by_name["a"].status == "active"
        assert by_name["b"].status == "paused"


# ---------------------------------------------------------------------------
# rollback_to_version
# ---------------------------------------------------------------------------


class TestRollbackToVersion:
    async def test_rollback_restores_prior_snapshot(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])  # v1
        await svc.bulk_sync_with_version([_cfg("a")])  # v2 → b paused

        # Build a fresh service so the in-memory cache is cold (forces DB read)
        fresh = SubscriptionService(session)
        result = await fresh.rollback_to_version("1")
        assert result["rolled_back_to"] == "1"
        assert result["config_count"] == 2
        assert sorted(result["subscription_names"]) == ["a", "b"]
        rows = (await session.execute(select(Subscription))).scalars().all()
        by_name = {r.name: r for r in rows}
        assert by_name["b"].status == "active", (
            "rollback to v1 must reactivate 'b' which v2 had paused"
        )

    async def test_rollback_unknown_version_raises(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        with pytest.raises(ValueError, match="not found"):
            await svc.rollback_to_version("99")


# ---------------------------------------------------------------------------
# get / list_versions / diff_with_yaml
# ---------------------------------------------------------------------------


class TestGet:
    async def test_get_returns_subscription_by_id(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        created = await svc.create(_cfg("g"))
        fetched = await svc.get(created.id)
        assert fetched is not None
        assert fetched.name == "g"

    async def test_get_missing_id_returns_none(self, session: AsyncSession) -> None:
        svc = SubscriptionService(session)
        assert await svc.get(uuid.uuid4()) is None


class TestListVersions:
    async def test_list_versions_newest_first_with_count(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        await svc.bulk_sync_with_version([_cfg("a")])  # v1, 1 config
        await svc.bulk_sync_with_version([_cfg("a"), _cfg("b")])  # v2, 2 configs

        versions = await svc.list_versions(limit=10)
        assert [v["version"] for v in versions] == ["2", "1"]
        assert versions[0]["config_count"] == 2
        assert versions[1]["config_count"] == 1


class TestDiffWithYaml:
    async def test_diff_partitions_names_and_marks_pause(
        self, session: AsyncSession
    ) -> None:
        svc = SubscriptionService(session)
        # DB has 'keep' (also in yaml) and 'gone' (yaml-removed).
        await svc.create(_cfg("keep"))
        await svc.create(_cfg("gone"))

        diff = await svc.diff_with_yaml([_cfg("keep"), _cfg("fresh")])
        assert diff["yaml_only"] == ["fresh"]
        assert diff["db_only"] == ["gone"]
        assert diff["both"] == ["keep"]
        # subscriptions reload is a full sync → db-only rows get paused.
        assert diff["db_only_action"] == "pause"
