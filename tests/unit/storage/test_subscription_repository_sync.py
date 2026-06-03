"""Tests for SubscriptionRepository.upsert + bulk_sync_from_configs (B-054 Phase 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import Text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.storage.models import Base, Subscription
from intellisource.storage.repositories.subscription import SubscriptionRepository

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base: type[Base]) -> None:
    for table in base.metadata.tables.values():
        to_remove = []
        for idx in table.indexes:
            dialect_opts = getattr(idx, "dialect_options", {})
            pg = dialect_opts.get("postgresql", {})
            if pg.get("using") or pg.get("ops"):
                to_remove.append(idx)
        for idx in to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):  # type: ignore[no-untyped-def]
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
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        yield sess


def _cfg(name: str, channel: str = "wework", **overrides: object) -> SubscriptionConfig:
    base = {
        "name": name,
        "channel": channel,
        "channel_config": {"user_id": "@all", "msg_type": "text"}
        if channel == "wework"
        else {"to_addr": "u@example.com"}
        if channel == "email"
        else {},
        "match_rules": {"tags": ["x"]},
    }
    base.update(overrides)
    return SubscriptionConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# upsert by name
# ---------------------------------------------------------------------------


class TestUpsertByName:
    async def test_upsert_creates_new_subscription_when_name_absent(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        created = await repo.upsert(_cfg("new-sub"))
        assert created.name == "new-sub"
        assert created.channel == "wework"
        assert created.status == "active"

    async def test_upsert_updates_existing_subscription_with_same_name(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        first = await repo.upsert(_cfg("sub", channel="email"))
        first_id = first.id

        # Re-upsert with mutated channel_config + match_rules
        updated_cfg = _cfg(
            "sub",
            channel="email",
            channel_config={"to_addr": "new@x.com"},
            match_rules={"tags": ["ai", "ml"]},
        )
        updated = await repo.upsert(updated_cfg)

        assert updated.id == first_id, "upsert must update in-place, not duplicate"
        assert updated.channel_config["to_addr"] == "new@x.com"
        assert updated.match_rules["tags"] == ["ai", "ml"]
        # Regression: the UPDATE branch must refresh so onupdate ``updated_at`` is
        # loaded, not expired (an expired attr lazy-loads on the next sync access →
        # MissingGreenlet during router serialization).
        from sqlalchemy import inspect as sa_inspect

        assert "updated_at" not in sa_inspect(updated).unloaded
        assert updated.updated_at is not None

    async def test_upsert_reactivates_paused_subscription(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        sub = await repo.upsert(_cfg("revive"))
        sub.status = "paused"
        await session.flush()

        revived = await repo.upsert(_cfg("revive"))
        assert revived.status == "active", (
            "paused subscription must flip back to active"
        )


# ---------------------------------------------------------------------------
# bulk_sync_from_configs
# ---------------------------------------------------------------------------


class TestBulkSyncFromConfigs:
    async def test_bulk_sync_creates_all_new(self, session: AsyncSession) -> None:
        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs([_cfg("a"), _cfg("b"), _cfg("c")])
        rows = (await session.execute(select(Subscription))).scalars().all()
        names = sorted(r.name for r in rows)
        assert names == ["a", "b", "c"]
        assert all(r.status == "active" for r in rows)

    async def test_bulk_sync_marks_absent_as_paused(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs([_cfg("a"), _cfg("b"), _cfg("c")])

        # Second sync drops 'b' from yaml
        await repo.bulk_sync_from_configs([_cfg("a"), _cfg("c")])
        rows = (await session.execute(select(Subscription))).scalars().all()
        by_name = {r.name: r for r in rows}
        assert by_name["a"].status == "active"
        assert by_name["b"].status == "paused", (
            "Subscription absent from yaml must be soft-deleted (status=paused), "
            "not physically removed"
        )
        assert by_name["c"].status == "active"

    async def test_bulk_sync_empty_pauses_all(self, session: AsyncSession) -> None:
        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs([_cfg("a"), _cfg("b")])
        await repo.bulk_sync_from_configs([])
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert all(r.status == "paused" for r in rows)

    async def test_bulk_sync_updates_channel_config_in_place(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs(
            [_cfg("sub", channel="wework", channel_config={"user_id": "@all"})]
        )
        await repo.bulk_sync_from_configs(
            [
                _cfg(
                    "sub",
                    channel="wework",
                    channel_config={"user_id": "ZhangSan", "msg_type": "markdown"},
                )
            ]
        )
        rows = (await session.execute(select(Subscription))).scalars().all()
        assert len(rows) == 1
        assert rows[0].channel_config["user_id"] == "ZhangSan"
        assert rows[0].channel_config["msg_type"] == "markdown"

    async def test_bulk_sync_reactivates_when_yaml_reintroduces_paused(
        self, session: AsyncSession
    ) -> None:
        repo = SubscriptionRepository(session)
        await repo.bulk_sync_from_configs([_cfg("sub")])
        await repo.bulk_sync_from_configs([])  # paused
        rows_before = (await session.execute(select(Subscription))).scalars().all()
        assert rows_before[0].status == "paused"

        await repo.bulk_sync_from_configs([_cfg("sub")])
        rows_after = (await session.execute(select(Subscription))).scalars().all()
        assert rows_after[0].status == "active"
