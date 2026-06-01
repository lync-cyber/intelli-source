"""discipline_tags persistence link: SourceConfig → Source → ProcessedContent.

Covers the previously half-wired discipline axis — the matcher reads
``content.discipline_tags`` but no column/persistence existed to populate it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from intellisource.config.models import SourceConfig
from intellisource.distributor.matcher import SubscriptionMatcher
from intellisource.storage.models import Base, ProcessedContent, RawContent, Source
from intellisource.storage.repositories.content import ContentRepository
from intellisource.storage.repositories.source import SourceRepository

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _set_fk(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


@pytest.fixture
async def session():
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)
    event.listen(eng.sync_engine, "connect", _set_fk)
    for table in Base.metadata.tables.values():
        for idx in list(table.indexes):
            pg = getattr(idx, "dialect_options", {}).get("postgresql", {})
            if pg.get("using") or pg.get("ops"):
                table.indexes.discard(idx)
        for col in table.columns:
            if type(col.type).__name__ == "Vector":
                col.type = Text()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


class TestSourceDisciplineTags:
    async def test_upsert_persists_discipline_tags(self, session: AsyncSession) -> None:
        repo = SourceRepository(session)
        await repo.upsert(
            SourceConfig(
                name="ee-src",
                type="rss",
                url="https://example.com/ee.rss",
                discipline_tags=["电气工程"],
            )
        )
        row = (await session.execute(select(Source))).scalar_one()
        assert list(row.discipline_tags) == ["电气工程"]

    async def test_bulk_sync_updates_discipline_tags(
        self, session: AsyncSession
    ) -> None:
        repo = SourceRepository(session)
        await repo.upsert(SourceConfig(name="s", type="rss", url="https://e.com/x.rss"))
        await repo.bulk_sync_from_configs(
            [
                SourceConfig(
                    name="s",
                    type="rss",
                    url="https://e.com/x.rss",
                    discipline_tags=["计算机科学"],
                )
            ]
        )
        row = (await session.execute(select(Source))).scalar_one()
        assert list(row.discipline_tags) == ["计算机科学"]


class TestProcessedContentDisciplineTags:
    async def _make_raw(self, session: AsyncSession) -> RawContent:
        source = Source(
            id=uuid.uuid4(),
            name="src",
            type="rss",
            url="https://e.com/f.rss",
            discipline_tags=["电气工程"],
        )
        session.add(source)
        await session.flush()
        raw = RawContent(
            id=uuid.uuid4(),
            source_id=source.id,
            source_url="https://e.com/a",
            fingerprint="fp-1",
            title="t",
            body_text="b",
        )
        session.add(raw)
        await session.flush()
        return raw

    async def test_create_persists_discipline_tags(self, session: AsyncSession) -> None:
        raw = await self._make_raw(session)
        repo = ContentRepository(session)
        await repo.create(
            raw_content_id=raw.id,
            title="t",
            body_text="b",
            discipline_tags=["电气工程"],
            source_name="src",
        )
        row = (await session.execute(select(ProcessedContent))).scalar_one()
        assert list(row.discipline_tags) == ["电气工程"]
        assert row.source_name == "src"

    async def test_persisted_content_matches_discipline_subscription(
        self, session: AsyncSession
    ) -> None:
        raw = await self._make_raw(session)
        repo = ContentRepository(session)
        await repo.create(
            raw_content_id=raw.id,
            title="电网调度",
            body_text="正文",
            discipline_tags=["电气工程"],
            source_name="src",
        )
        content = (await session.execute(select(ProcessedContent))).scalar_one()

        sub = type(
            "Sub",
            (),
            {
                "status": "active",
                "match_rules": {"discipline_tags": ["电气工程"]},
            },
        )()
        matched = SubscriptionMatcher().match(content, [sub])
        assert matched == [sub]
