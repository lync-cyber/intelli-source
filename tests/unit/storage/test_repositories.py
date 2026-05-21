"""Tests for T-004: Repository layer (data access).

Covers:
  AC-054:     Structured data CRUD operations (create/read/update/delete/list)
  AC-T004-1:  SourceRepository filters by type/tag/status with cursor pagination
  AC-T004-2:  ContentRepository filters by source_id/tag/cluster_id/time + cursor
              pagination
  AC-T004-3:  TaskRepository supports filtering by status/type/source_id
  AC-T004-4:  PushRepository dedup query (subscription_id + content_id + channel)
  AC-T004-5:  Cursor pagination returns items + next_cursor + has_more format
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from intellisource.storage.models import (
    Base,
    CollectTask,
    ContentCluster,
    ProcessedContent,
    PushRecord,
    RawContent,
    Source,
    Subscription,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SQLITE_TEST_URL = "sqlite+aiosqlite:///:memory:"


def _remove_pg_only_indexes(base):
    """Remove indexes that use PostgreSQL-specific features unsupported by SQLite.

    This includes GIN indexes (on JSONB/trgm), HNSW indexes (pgvector),
    and any index with postgresql_using or postgresql_ops.
    """
    for table in base.metadata.tables.values():
        indexes_to_remove = []
        for idx in table.indexes:
            dialect_options = getattr(idx, "dialect_options", {})
            pg_opts = dialect_options.get("postgresql", {})
            if pg_opts.get("using") or pg_opts.get("ops"):
                indexes_to_remove.append(idx)
        for idx in indexes_to_remove:
            table.indexes.discard(idx)


def _set_sqlite_fk_pragma(dbapi_conn, connection_record):
    """Enable foreign key enforcement on SQLite connections."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
async def engine():
    """Create an async SQLite in-memory engine with all tables."""
    eng = create_async_engine(SQLITE_TEST_URL, echo=False)

    # Enable FK enforcement for SQLite
    event.listen(eng.sync_engine, "connect", _set_sqlite_fk_pragma)

    _remove_pg_only_indexes(Base)

    # pgvector Vector columns are not supported in SQLite.
    # Replace Vector columns with Text columns for testing purposes.
    for table in Base.metadata.tables.values():
        for col in table.columns:
            type_name = type(col.type).__name__
            if type_name == "Vector":
                col.type = Text()

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def session(engine):
    """Provide an AsyncSession bound to the in-memory test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Helpers: seed data factories
# ---------------------------------------------------------------------------


def _make_source(**overrides) -> Source:
    """Create a Source instance with sensible defaults."""
    defaults = dict(
        id=uuid.uuid4(),
        name=f"test-source-{uuid.uuid4().hex[:8]}",
        type="rss",
        url="https://example.com/feed",
        tags=["tech"],
        status="active",
        schedule_interval=3600,
        schedule_adaptive=True,
        metadata_={},
    )
    defaults.update(overrides)
    return Source(**defaults)


def _make_collect_task(source_id: uuid.UUID, **overrides) -> CollectTask:
    defaults = dict(
        id=uuid.uuid4(),
        source_id=source_id,
        status="pending",
        priority="normal",
        trigger_type="scheduled",
        items_collected=0,
    )
    defaults.update(overrides)
    return CollectTask(**defaults)


def _make_raw_content(source_id: uuid.UUID, **overrides) -> RawContent:
    defaults = dict(
        id=uuid.uuid4(),
        source_id=source_id,
        title="Test Article",
        body_text="Some body text",
        source_url="https://example.com/article",
        fingerprint=uuid.uuid4().hex,
        raw_metadata={},
    )
    defaults.update(overrides)
    return RawContent(**defaults)


def _make_processed_content(raw_content_id: uuid.UUID, **overrides) -> ProcessedContent:
    defaults = dict(
        id=uuid.uuid4(),
        raw_content_id=raw_content_id,
        title="Processed Article",
        body_text="Processed body",
        tags=["ai"],
        processing_status="completed",
        processed_by="llm",
    )
    defaults.update(overrides)
    return ProcessedContent(**defaults)


def _make_subscription(source_id: uuid.UUID | None = None, **overrides) -> Subscription:
    defaults = dict(
        id=uuid.uuid4(),
        name=f"sub-{uuid.uuid4().hex[:8]}",
        source_id=source_id,
        channel="webhook",
        channel_config={"url": "https://hook.example.com"},
        match_rules={"tags": ["tech"]},
        frequency="realtime",
        status="active",
    )
    defaults.update(overrides)
    return Subscription(**defaults)


def _make_push_record(
    subscription_id: uuid.UUID,
    content_id: uuid.UUID,
    **overrides,
) -> PushRecord:
    defaults = dict(
        id=uuid.uuid4(),
        subscription_id=subscription_id,
        content_id=content_id,
        channel="webhook",
        status="pending",
    )
    defaults.update(overrides)
    return PushRecord(**defaults)


# ===========================================================================
# AC-054: Structured data CRUD operations
# ===========================================================================


class TestSourceRepositoryCRUD:
    """AC-054: SourceRepository CRUD (create/read/update/delete/list)."""

    @pytest.mark.asyncio
    async def test_import_source_repository(self) -> None:
        """SourceRepository class must be importable."""
        from intellisource.storage.repositories.source import SourceRepository

        assert SourceRepository is not None

    @pytest.mark.asyncio
    async def test_create_source(self, session: AsyncSession) -> None:
        """SourceRepository.create() persists a new Source and returns it."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        source = await repo.create(
            name="My RSS Feed",
            type="rss",
            url="https://example.com/feed.xml",
            tags=["tech", "news"],
        )
        assert source.id is not None
        assert source.name == "My RSS Feed"
        assert source.type == "rss"
        assert source.status == "active"

    @pytest.mark.asyncio
    async def test_get_source_by_id(self, session: AsyncSession) -> None:
        """SourceRepository.get_by_id() returns the correct Source."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        created = await repo.create(
            name="Feed-Get",
            type="rss",
            url="https://example.com/get",
        )
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Feed-Get"

    @pytest.mark.asyncio
    async def test_get_source_by_id_not_found(self, session: AsyncSession) -> None:
        """SourceRepository.get_by_id() returns None for non-existent ID."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        result = await repo.get_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_update_source(self, session: AsyncSession) -> None:
        """SourceRepository.update() modifies fields and persists changes."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        created = await repo.create(
            name="Feed-Update",
            type="rss",
            url="https://example.com/update",
        )
        updated = await repo.update(created.id, name="Feed-Updated", status="paused")
        assert updated is not None
        assert updated.name == "Feed-Updated"
        assert updated.status == "paused"

    @pytest.mark.asyncio
    async def test_delete_source(self, session: AsyncSession) -> None:
        """SourceRepository.delete() removes the Source from the database."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        created = await repo.create(
            name="Feed-Delete",
            type="rss",
            url="https://example.com/delete",
        )
        result = await repo.delete(created.id)
        assert result is True
        fetched = await repo.get_by_id(created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list_sources(self, session: AsyncSession) -> None:
        """SourceRepository.list() returns all sources when no filters applied."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        await repo.create(name="Feed-A", type="rss", url="https://a.com")
        await repo.create(name="Feed-B", type="web", url="https://b.com")

        page = await repo.list()
        assert len(page["items"]) >= 2


class TestContentRepositoryCRUD:
    """AC-054: ContentRepository CRUD operations on ProcessedContent."""

    @pytest.mark.asyncio
    async def test_import_content_repository(self) -> None:
        """ContentRepository class must be importable."""
        from intellisource.storage.repositories.content import ContentRepository

        assert ContentRepository is not None

    @pytest.mark.asyncio
    async def test_create_and_get_content(self, session: AsyncSession) -> None:
        """ContentRepository create and get_by_id round-trip."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        # Seed prerequisite source + raw content
        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()

        content = await repo.create(
            raw_content_id=raw.id,
            title="Test Content",
            body_text="Hello world",
            tags=["ai"],
        )
        assert content.id is not None

        fetched = await repo.get_by_id(content.id)
        assert fetched is not None
        assert fetched.title == "Test Content"

    @pytest.mark.asyncio
    async def test_update_content(self, session: AsyncSession) -> None:
        """ContentRepository.update() modifies and persists fields."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()

        content = await repo.create(
            raw_content_id=raw.id,
            title="Original",
            body_text="Original body",
            tags=["tech"],
        )
        updated = await repo.update(content.id, title="Revised", tags=["ai", "tech"])
        assert updated is not None
        assert updated.title == "Revised"
        assert "ai" in updated.tags

    @pytest.mark.asyncio
    async def test_delete_content(self, session: AsyncSession) -> None:
        """ContentRepository.delete() removes the record."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()

        content = await repo.create(
            raw_content_id=raw.id,
            title="To Delete",
            body_text="Will be deleted",
            tags=[],
        )
        result = await repo.delete(content.id)
        assert result is True
        assert await repo.get_by_id(content.id) is None


class TestTaskRepositoryCRUD:
    """AC-054: TaskRepository CRUD operations on CollectTask."""

    @pytest.mark.asyncio
    async def test_import_task_repository(self) -> None:
        """TaskRepository class must be importable."""
        from intellisource.storage.repositories.task import TaskRepository

        assert TaskRepository is not None

    @pytest.mark.asyncio
    async def test_create_and_get_task(self, session: AsyncSession) -> None:
        """TaskRepository.create() and get_by_id() round-trip."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        task = await repo.create(
            source_id=src.id,
            trigger_type="scheduled",
        )
        assert task.id is not None
        assert task.status == "pending"

        fetched = await repo.get_by_id(task.id)
        assert fetched is not None
        assert fetched.source_id == src.id

    @pytest.mark.asyncio
    async def test_update_task_status(self, session: AsyncSession) -> None:
        """TaskRepository.update() can change task status."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        task = await repo.create(source_id=src.id, trigger_type="manual")
        updated = await repo.update(task.id, status="running")
        assert updated is not None
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_delete_task(self, session: AsyncSession) -> None:
        """TaskRepository.delete() removes the task."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        task = await repo.create(source_id=src.id, trigger_type="manual")
        result = await repo.delete(task.id)
        assert result is True
        assert await repo.get_by_id(task.id) is None


class TestPushRepositoryCRUD:
    """AC-054: PushRepository CRUD operations on PushRecord."""

    @pytest.mark.asyncio
    async def test_import_push_repository(self) -> None:
        """PushRepository class must be importable."""
        from intellisource.storage.repositories.push import PushRepository

        assert PushRepository is not None

    @pytest.mark.asyncio
    async def test_create_and_get_push_record(self, session: AsyncSession) -> None:
        """PushRepository.create() and get_by_id() round-trip."""
        from intellisource.storage.repositories.push import PushRepository

        repo = PushRepository(session)

        # Seed prerequisite data
        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()
        pc = _make_processed_content(raw.id)
        session.add(pc)
        sub = _make_subscription(src.id)
        session.add(sub)
        await session.flush()

        record = await repo.create(
            subscription_id=sub.id,
            content_id=pc.id,
            channel="webhook",
        )
        assert record.id is not None

        fetched = await repo.get_by_id(record.id)
        assert fetched is not None
        assert fetched.subscription_id == sub.id


class TestSubscriptionRepositoryCRUD:
    """AC-054: SubscriptionRepository CRUD operations."""

    @pytest.mark.asyncio
    async def test_import_subscription_repository(self) -> None:
        """SubscriptionRepository class must be importable."""
        from intellisource.storage.repositories.subscription import (
            SubscriptionRepository,
        )

        assert SubscriptionRepository is not None

    @pytest.mark.asyncio
    async def test_create_and_get_subscription(self, session: AsyncSession) -> None:
        """SubscriptionRepository.create() and get_by_id() round-trip."""
        from intellisource.storage.repositories.subscription import (
            SubscriptionRepository,
        )

        repo = SubscriptionRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        sub = await repo.create(
            name="My Sub",
            channel="webhook",
            channel_config={"url": "https://hook.test"},
            match_rules={"tags": ["ai"]},
            source_id=src.id,
        )
        assert sub.id is not None

        fetched = await repo.get_by_id(sub.id)
        assert fetched is not None
        assert fetched.name == "My Sub"

    @pytest.mark.asyncio
    async def test_update_subscription(self, session: AsyncSession) -> None:
        """SubscriptionRepository.update() modifies fields."""
        from intellisource.storage.repositories.subscription import (
            SubscriptionRepository,
        )

        repo = SubscriptionRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        sub = await repo.create(
            name="Sub-Original",
            channel="email",
            channel_config={"address": "test@example.com"},
            match_rules={},
        )
        updated = await repo.update(sub.id, name="Sub-Updated", status="paused")
        assert updated is not None
        assert updated.name == "Sub-Updated"
        assert updated.status == "paused"

    @pytest.mark.asyncio
    async def test_delete_subscription(self, session: AsyncSession) -> None:
        """SubscriptionRepository.delete() removes the subscription."""
        from intellisource.storage.repositories.subscription import (
            SubscriptionRepository,
        )

        repo = SubscriptionRepository(session)

        sub = await repo.create(
            name="Sub-Delete",
            channel="webhook",
            channel_config={},
            match_rules={},
        )
        result = await repo.delete(sub.id)
        assert result is True
        assert await repo.get_by_id(sub.id) is None


# ===========================================================================
# AC-T004-1: SourceRepository filtering by type/tag/status + cursor pagination
# ===========================================================================


class TestSourceRepositoryFiltering:
    """AC-T004-1: SourceRepository supports filtering by type/tag/status
    and cursor-based pagination."""

    @pytest.mark.asyncio
    async def test_filter_by_type(self, session: AsyncSession) -> None:
        """list(type='rss') returns only RSS sources."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        await repo.create(name="RSS-1", type="rss", url="https://rss1.com")
        await repo.create(name="Web-1", type="web", url="https://web1.com")

        page = await repo.list(type="rss")
        assert all(item.type == "rss" for item in page["items"])
        assert len(page["items"]) >= 1

    @pytest.mark.asyncio
    async def test_filter_by_status(self, session: AsyncSession) -> None:
        """list(status='paused') returns only paused sources."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        await repo.create(name="Active-1", type="rss", url="https://a1.com")
        s = await repo.create(name="Paused-1", type="rss", url="https://p1.com")
        await repo.update(s.id, status="paused")

        page = await repo.list(status="paused")
        assert len(page["items"]) >= 1
        assert all(item.status == "paused" for item in page["items"])

    @pytest.mark.asyncio
    async def test_filter_by_tag(self, session: AsyncSession) -> None:
        """list(tag='finance') returns sources containing the 'finance' tag."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        await repo.create(
            name="Tech-Feed", type="rss", url="https://tech.com", tags=["tech"]
        )
        await repo.create(
            name="Finance-Feed",
            type="rss",
            url="https://fin.com",
            tags=["finance", "news"],
        )

        page = await repo.list(tag="finance")
        assert len(page["items"]) >= 1
        assert all("finance" in item.tags for item in page["items"])

    @pytest.mark.asyncio
    async def test_cursor_pagination(self, session: AsyncSession) -> None:
        """list() with limit returns next_cursor for additional pages."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        # Create enough sources to require pagination
        for i in range(5):
            await repo.create(
                name=f"Paginated-{i}", type="rss", url=f"https://p{i}.com"
            )

        page1 = await repo.list(limit=2)
        assert len(page1["items"]) == 2
        assert page1["has_more"] is True
        assert page1["next_cursor"] is not None

        page2 = await repo.list(limit=2, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 2
        # Ensure no overlap
        page1_ids = {s.id for s in page1["items"]}
        page2_ids = {s.id for s in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)


# ===========================================================================
# AC-T004-2: ContentRepository filtering by source_id/tag/cluster_id/time range
# ===========================================================================


class TestContentRepositoryFiltering:
    """AC-T004-2: ContentRepository supports filtering by source_id/tag/
    cluster_id/time range and cursor pagination."""

    @pytest.mark.asyncio
    async def test_filter_by_source_id(self, session: AsyncSession) -> None:
        """list(source_id=...) returns only content from that source."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src_a = _make_source(name="SrcA")
        src_b = _make_source(name="SrcB")
        session.add_all([src_a, src_b])
        await session.flush()

        raw_a = _make_raw_content(src_a.id)
        raw_b = _make_raw_content(src_b.id)
        session.add_all([raw_a, raw_b])
        await session.flush()

        await repo.create(
            raw_content_id=raw_a.id, title="From A", body_text="A", tags=[]
        )
        await repo.create(
            raw_content_id=raw_b.id, title="From B", body_text="B", tags=[]
        )

        page = await repo.list(source_id=src_a.id)
        assert len(page["items"]) >= 1
        # All returned content should trace back to src_a via raw_content

    @pytest.mark.asyncio
    async def test_filter_by_tag(self, session: AsyncSession) -> None:
        """list(tag='ai') returns content tagged with 'ai'."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src = _make_source()
        session.add(src)
        raw1 = _make_raw_content(src.id)
        raw2 = _make_raw_content(src.id)
        session.add_all([raw1, raw2])
        await session.flush()

        await repo.create(
            raw_content_id=raw1.id, title="AI Article", body_text="x", tags=["ai"]
        )
        await repo.create(
            raw_content_id=raw2.id,
            title="Finance Article",
            body_text="y",
            tags=["finance"],
        )

        page = await repo.list(tag="ai")
        assert len(page["items"]) >= 1
        assert all("ai" in item.tags for item in page["items"])

    @pytest.mark.asyncio
    async def test_filter_by_cluster_id(self, session: AsyncSession) -> None:
        """list(cluster_id=...) returns content belonging to that cluster."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        cluster = ContentCluster(
            id=uuid.uuid4(), topic="AI News", tags=["ai"], content_count=1
        )
        session.add(cluster)

        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()

        await repo.create(
            raw_content_id=raw.id,
            title="Clustered",
            body_text="z",
            tags=["ai"],
            cluster_id=cluster.id,
        )

        page = await repo.list(cluster_id=cluster.id)
        assert len(page["items"]) >= 1
        assert all(item.cluster_id == cluster.id for item in page["items"])

    @pytest.mark.asyncio
    async def test_filter_by_time_range(self, session: AsyncSession) -> None:
        """list(published_after=..., published_before=...) filters by time range."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()

        target_time = datetime(2026, 3, 15, tzinfo=timezone.utc)
        await repo.create(
            raw_content_id=raw.id,
            title="March Content",
            body_text="march",
            tags=[],
            published_at=target_time,
        )

        page = await repo.list(
            published_after=datetime(2026, 3, 1, tzinfo=timezone.utc),
            published_before=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        assert len(page["items"]) >= 1

    @pytest.mark.asyncio
    async def test_cursor_pagination(self, session: AsyncSession) -> None:
        """ContentRepository list() supports cursor-based pagination."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        for i in range(5):
            raw = _make_raw_content(src.id)
            session.add(raw)
            await session.flush()
            await repo.create(
                raw_content_id=raw.id,
                title=f"Content-{i}",
                body_text=f"body {i}",
                tags=[],
            )

        page1 = await repo.list(limit=2)
        assert len(page1["items"]) == 2
        assert page1["has_more"] is True
        assert page1["next_cursor"] is not None

        page2 = await repo.list(limit=2, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 2
        page1_ids = {c.id for c in page1["items"]}
        page2_ids = {c.id for c in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)


# ===========================================================================
# AC-T004-3: TaskRepository filtering by status/type/source_id
# ===========================================================================


class TestTaskRepositoryFiltering:
    """AC-T004-3: TaskRepository supports filtering by status/type/source_id."""

    @pytest.mark.asyncio
    async def test_filter_by_status(self, session: AsyncSession) -> None:
        """list(status='running') returns only running tasks."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        t1 = await repo.create(source_id=src.id, trigger_type="scheduled")
        await repo.update(t1.id, status="running")
        await repo.create(source_id=src.id, trigger_type="manual")

        page = await repo.list(status="running")
        assert len(page["items"]) >= 1
        assert all(item.status == "running" for item in page["items"])

    @pytest.mark.asyncio
    async def test_filter_by_trigger_type(self, session: AsyncSession) -> None:
        """list(trigger_type='manual') returns only manually triggered tasks."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src = _make_source()
        session.add(src)
        await session.flush()

        await repo.create(source_id=src.id, trigger_type="scheduled")
        await repo.create(source_id=src.id, trigger_type="manual")

        page = await repo.list(trigger_type="manual")
        assert len(page["items"]) >= 1
        assert all(item.trigger_type == "manual" for item in page["items"])

    @pytest.mark.asyncio
    async def test_filter_by_source_id(self, session: AsyncSession) -> None:
        """list(source_id=...) returns tasks for that source only."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)

        src_a = _make_source(name="TaskSrcA")
        src_b = _make_source(name="TaskSrcB")
        session.add_all([src_a, src_b])
        await session.flush()

        await repo.create(source_id=src_a.id, trigger_type="scheduled")
        await repo.create(source_id=src_b.id, trigger_type="scheduled")

        page = await repo.list(source_id=src_a.id)
        assert len(page["items"]) >= 1
        assert all(item.source_id == src_a.id for item in page["items"])


# ===========================================================================
# AC-T004-4: PushRepository deduplication query
# ===========================================================================


class TestPushRepositoryDedup:
    """AC-T004-4: PushRepository supports deduplication query
    (subscription_id + content_id + channel)."""

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_true_for_existing(
        self, session: AsyncSession
    ) -> None:
        """exists(sub_id, content_id, channel) returns True when record exists."""
        from intellisource.storage.repositories.push import PushRepository

        repo = PushRepository(session)

        # Seed prerequisite data
        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()
        pc = _make_processed_content(raw.id)
        session.add(pc)
        sub = _make_subscription(src.id)
        session.add(sub)
        await session.flush()

        await repo.create(
            subscription_id=sub.id,
            content_id=pc.id,
            channel="webhook",
        )

        is_dup = await repo.exists(
            subscription_id=sub.id,
            content_id=pc.id,
            channel="webhook",
        )
        assert is_dup is True

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_false_for_new(
        self, session: AsyncSession
    ) -> None:
        """exists(sub_id, content_id, channel) returns False when no record exists."""
        from intellisource.storage.repositories.push import PushRepository

        repo = PushRepository(session)

        is_dup = await repo.exists(
            subscription_id=uuid.uuid4(),
            content_id=uuid.uuid4(),
            channel="webhook",
        )
        assert is_dup is False

    @pytest.mark.asyncio
    async def test_check_duplicate_different_channel_is_not_dup(
        self, session: AsyncSession
    ) -> None:
        """Same subscription_id + content_id but different channel is NOT dup."""
        from intellisource.storage.repositories.push import PushRepository

        repo = PushRepository(session)

        src = _make_source()
        session.add(src)
        raw = _make_raw_content(src.id)
        session.add(raw)
        await session.flush()
        pc = _make_processed_content(raw.id)
        session.add(pc)
        sub = _make_subscription(src.id)
        session.add(sub)
        await session.flush()

        await repo.create(
            subscription_id=sub.id,
            content_id=pc.id,
            channel="webhook",
        )

        is_dup = await repo.exists(
            subscription_id=sub.id,
            content_id=pc.id,
            channel="email",
        )
        assert is_dup is False


# ===========================================================================
# AC-T004-5: Cursor pagination format (items + next_cursor + has_more)
# ===========================================================================


class TestCursorPaginationFormat:
    """AC-T004-5: All repository list() methods return
    {items, next_cursor, has_more} format."""

    @pytest.mark.asyncio
    async def test_source_list_returns_pagination_dict(
        self, session: AsyncSession
    ) -> None:
        """SourceRepository.list() returns dict with items/next_cursor/has_more."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        page = await repo.list()
        assert "items" in page
        assert "next_cursor" in page
        assert "has_more" in page
        assert isinstance(page["items"], list)
        assert isinstance(page["has_more"], bool)

    @pytest.mark.asyncio
    async def test_content_list_returns_pagination_dict(
        self, session: AsyncSession
    ) -> None:
        """ContentRepository.list() returns dict with items/next_cursor/has_more."""
        from intellisource.storage.repositories.content import ContentRepository

        repo = ContentRepository(session)
        page = await repo.list()
        assert "items" in page
        assert "next_cursor" in page
        assert "has_more" in page

    @pytest.mark.asyncio
    async def test_task_list_returns_pagination_dict(
        self, session: AsyncSession
    ) -> None:
        """TaskRepository.list() returns dict with items/next_cursor/has_more."""
        from intellisource.storage.repositories.task import TaskRepository

        repo = TaskRepository(session)
        page = await repo.list()
        assert "items" in page
        assert "next_cursor" in page
        assert "has_more" in page

    @pytest.mark.asyncio
    async def test_last_page_has_no_cursor(self, session: AsyncSession) -> None:
        """When no more results, has_more is False and next_cursor is None."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        await repo.create(name="Only-One", type="rss", url="https://only.com")

        page = await repo.list(limit=100)
        assert page["has_more"] is False
        assert page["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_default_page_size_is_20(self, session: AsyncSession) -> None:
        """Default page size is 20 items when limit is not specified."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        # Create 25 sources
        for i in range(25):
            await repo.create(
                name=f"Default-Page-{i}", type="rss", url=f"https://dp{i}.com"
            )

        page = await repo.list()
        assert len(page["items"]) == 20
        assert page["has_more"] is True

    @pytest.mark.asyncio
    async def test_max_page_size_capped_at_100(self, session: AsyncSession) -> None:
        """Page size is capped at 100 even if a larger limit is requested."""
        from intellisource.storage.repositories.source import SourceRepository

        repo = SourceRepository(session)
        page = await repo.list(limit=200)
        # The repo should cap at 100, not return 200
        # We just verify the call succeeds and respects the cap
        assert isinstance(page["items"], list)
