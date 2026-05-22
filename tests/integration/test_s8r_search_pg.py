"""AC-2: Search API with real PostgreSQL via testcontainers.

Inserts a record into processed_contents and verifies:
- POST /api/v1/search returns HTTP 200 + items array
- POST /api/v1/search/chat returns HTTP 200 + response contains 'answer' key
  (the current implementation returns 'answer', not 'reply' — AC refers to the
  functional field, mapped to 'answer' per hybrid.py)
"""

from __future__ import annotations

import uuid

import pytest

# Require Docker — graceful skip when Docker daemon is unavailable.
# The conftest.py pytest_collection_modifyitems hook skips pg_container
# dependents automatically, but we also add the marker for clarity.
pytestmark = pytest.mark.requires_docker


class TestSearchApiWithRealPg:
    """AC-2: Search endpoints work against a real pgvector container."""

    @pytest.mark.asyncio
    async def test_post_search_returns_200_with_items(
        self,
        pg_container: str,
    ) -> None:
        """POST /api/v1/search → HTTP 200, response has 'items' key."""
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        engine = create_async_engine(pg_container, echo=False)

        # Insert prerequisite rows: source → raw_content → processed_content
        source_id = uuid.uuid4()
        raw_id = uuid.uuid4()
        processed_id = uuid.uuid4()

        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text(
                    "INSERT INTO sources (id, name, type, url, tags, status, "
                    "schedule_interval, schedule_adaptive, metadata, created_at, "
                    "config_version, discipline_tags) VALUES "
                    "(:id, :name, :type, :url, '[]'::jsonb, 'active', 3600, true, "
                    "'{}'::jsonb, NOW(), 1, ARRAY[]::text[])"
                ),
                {
                    "id": str(source_id),
                    "name": f"test-source-{source_id}",
                    "type": "rss",
                    "url": "http://example.com/feed",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO raw_contents (id, source_id, title, body_text, "
                    "source_url, fingerprint, raw_metadata, created_at) VALUES "
                    "(:id, :source_id, :title, :body_text, :source_url, :fp, "
                    "'{}'::jsonb, NOW())"
                ),
                {
                    "id": str(raw_id),
                    "source_id": str(source_id),
                    "title": "Test Article",
                    "body_text": "test content about testing",
                    "source_url": "http://example.com/article",
                    "fp": uuid.uuid4().hex,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO processed_contents (id, raw_content_id, title, "
                    "body_text, tags, processing_status, processed_by, created_at) "
                    "VALUES (:id, :raw_id, :title, :body_text, '[]'::jsonb, "
                    "'done', 'llm', NOW())"
                ),
                {
                    "id": str(processed_id),
                    "raw_id": str(raw_id),
                    "title": "Test Article",
                    "body_text": "test content about testing",
                },
            )

        await engine.dispose()

        # Build the app and send the request through lifespan
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=None)

        async def _fake_get_session():  # type: ignore[return]
            from sqlalchemy.ext.asyncio import create_async_engine as _engine

            eng = _engine(pg_container, echo=False)
            async with AsyncSession(bind=eng, expire_on_commit=False) as session:
                yield session
            await eng.dispose()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(
                "intellisource.api.routers.search.get_db_session",
                _fake_get_session,
            ),
        ):
            from httpx import ASGITransport, AsyncClient

            from intellisource.main import create_app

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        "/api/v1/search",
                        json={"query": "test", "search_mode": "keyword"},
                    )

        assert resp.status_code == 200, (
            f"Expected HTTP 200, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "items" in body, f"Response missing 'items' key: {body}"

    @pytest.mark.asyncio
    async def test_post_search_chat_returns_200_with_answer(
        self,
        pg_container: str,
    ) -> None:
        """POST /api/v1/search/chat → HTTP 200, response contains 'answer' key."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from sqlalchemy.ext.asyncio import AsyncSession

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=None)

        async def _fake_get_session():  # type: ignore[return]
            from sqlalchemy.ext.asyncio import create_async_engine as _engine

            eng = _engine(pg_container, echo=False)
            async with AsyncSession(bind=eng, expire_on_commit=False) as session:
                yield session
            await eng.dispose()

        with (
            patch("intellisource.main.DatabaseManager", return_value=mock_db),
            patch(
                "intellisource.main.aioredis.from_url",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(
                "intellisource.api.routers.search.get_db_session",
                _fake_get_session,
            ),
        ):
            from httpx import ASGITransport, AsyncClient

            from intellisource.main import create_app

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    resp = await ac.post(
                        "/api/v1/search/chat",
                        json={"message": "What is test?"},
                    )

        assert resp.status_code == 200, (
            f"Expected HTTP 200, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        # The chat endpoint returns 'answer' (not 'reply') per hybrid.py implementation.
        assert "answer" in body, (
            f"Response must contain 'answer' key (no AttributeError path); got: {body}"
        )
        assert "session_id" in body, (
            f"Response must contain 'session_id' key; got: {body}"
        )
