"""Tests for T-042: API routes -- content/search/subscription/LLM/system.

Covers:
  AC-T042-1: GET /api/v1/contents -- content list with pagination and filtering
  AC-T042-2: POST /api/v1/search -- hybrid search endpoint
  AC-T042-3: POST /api/v1/search/chat -- conversational search (instant Q&A)
  AC-T042-4: Subscription CRUD (/api/v1/subscriptions)
  AC-T042-5: GET /api/v1/llm/stats -- LLM usage statistics
  AC-T042-6: GET /api/v1/health and GET /api/v1/metrics -- system endpoints
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Router imports -- each router lives in its own module per dev-plan
# ---------------------------------------------------------------------------

try:
    from intellisource.api.routers.contents import (
        router as contents_router,  # type: ignore[import-untyped]
    )
except ImportError:
    contents_router = None  # type: ignore[assignment]

try:
    from intellisource.api.routers.search import (
        router as search_router,  # type: ignore[import-untyped]
    )
except ImportError:
    search_router = None  # type: ignore[assignment]

try:
    from intellisource.api.routers.subscriptions import (
        router as subscriptions_router,  # type: ignore[import-untyped]
    )
except ImportError:
    subscriptions_router = None  # type: ignore[assignment]

try:
    from intellisource.api.routers.llm import (
        router as llm_router,  # type: ignore[import-untyped]
    )
except ImportError:
    llm_router = None  # type: ignore[assignment]

try:
    from intellisource.api.routers.system import (
        router as system_router,  # type: ignore[import-untyped]
    )
except ImportError:
    system_router = None  # type: ignore[assignment]

_CONTENTS_MISSING = contents_router is None
_SEARCH_MISSING = search_router is None
_SUBSCRIPTIONS_MISSING = subscriptions_router is None
_LLM_MISSING = llm_router is None
_SYSTEM_MISSING = system_router is None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")
CONTENT_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000101")
SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
CLUSTER_ID = uuid.UUID("00000000-0000-0000-0000-000000000200")
SUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000300")
SUB_ID_2 = uuid.UUID("00000000-0000-0000-0000-000000000301")

# ---------------------------------------------------------------------------
# Mock object helpers
# ---------------------------------------------------------------------------


def _make_content_obj(
    *,
    id: uuid.UUID = CONTENT_ID,
    title: str = "Test Article",
    summary: str = "A short summary",
    tags: list[str] | None = None,
    source_name: str = "test-source",
    published_at: str = "2025-06-01T12:00:00+00:00",
    cluster_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a MagicMock that mimics a ProcessedContent / ContentBrief."""
    obj = MagicMock()
    obj.id = id
    obj.title = title
    obj.summary = summary
    obj.tags = tags or []
    obj.source_name = source_name
    obj.published_at = published_at
    obj.cluster_id = cluster_id
    obj.body_text = "Full article body text."
    obj.source_url = "https://example.com/article"
    obj.processing_status = "completed"
    obj.raw_content_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    obj.created_at = "2025-06-01T12:00:00+00:00"
    return obj


def _make_search_result(
    *,
    content_id: uuid.UUID = CONTENT_ID,
    title: str = "Search Result",
    snippet: str = "...matching text...",
    score: float = 0.95,
    source_name: str = "test-source",
    published_at: str = "2025-06-01T12:00:00+00:00",
) -> dict[str, Any]:
    """Return a dict representing a SearchResult."""
    return {
        "content_id": str(content_id),
        "title": title,
        "snippet": snippet,
        "score": score,
        "source_name": source_name,
        "published_at": published_at,
    }


def _make_subscription_obj(
    *,
    id: uuid.UUID = SUB_ID,
    name: str = "test-subscription",
    source_id: uuid.UUID | None = None,
    channel: str = "wechat",
    channel_config: dict[str, Any] | None = None,
    match_rules: dict[str, Any] | None = None,
    frequency: str = "realtime",
    status: str = "active",
) -> MagicMock:
    """Return a MagicMock that mimics a Subscription ORM instance."""
    obj = MagicMock()
    obj.id = id
    obj.name = name
    obj.source_id = source_id
    obj.channel = channel
    obj.channel_config = channel_config or {"openid": "test_openid"}
    obj.match_rules = match_rules or {"keywords": ["AI"]}
    obj.frequency = frequency
    obj.status = status
    obj.created_at = "2025-06-01T00:00:00+00:00"
    obj.updated_at = None
    return obj


# ---------------------------------------------------------------------------
# Fixtures -- one per router group
# ---------------------------------------------------------------------------


@pytest.fixture()
def contents_app() -> FastAPI:
    if _CONTENTS_MISSING:
        pytest.fail(
            "intellisource.api.routers.contents not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(contents_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def contents_client(contents_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=contents_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


@pytest.fixture()
def search_app() -> FastAPI:
    if _SEARCH_MISSING:
        pytest.fail(
            "intellisource.api.routers.search not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(search_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def search_client(search_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=search_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


@pytest.fixture()
def subscriptions_app() -> FastAPI:
    if _SUBSCRIPTIONS_MISSING:
        pytest.fail(
            "intellisource.api.routers.subscriptions missing: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(subscriptions_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def subscriptions_client(subscriptions_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=subscriptions_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


@pytest.fixture()
def llm_app() -> FastAPI:
    if _LLM_MISSING:
        pytest.fail(
            "intellisource.api.routers.llm not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(llm_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def llm_client(llm_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=llm_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


@pytest.fixture()
def system_app() -> FastAPI:
    if _SYSTEM_MISSING:
        pytest.fail(
            "intellisource.api.routers.system not implemented: cannot import 'router'"
        )
    application = FastAPI()
    application.include_router(system_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def system_client(system_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=system_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ===========================================================================
# AC-T042-1: GET /api/v1/contents -- content list with pagination & filtering
# ===========================================================================


class TestContentListEndpoint:
    """AC-T042-1: GET /api/v1/contents supports pagination and filtering."""

    @pytest.mark.asyncio
    async def test_list_contents_returns_paginated_result(
        self, contents_client: AsyncClient
    ) -> None:
        """Default GET returns items list with pagination metadata."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [_make_content_obj()],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.contents.ContentRepository",
            return_value=mock_repo,
        ):
            resp = await contents_client.get("/api/v1/contents")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 1
        assert "title" in body["items"][0]
        assert "summary" in body["items"][0]

    @pytest.mark.asyncio
    async def test_list_contents_filter_by_tag(
        self, contents_client: AsyncClient
    ) -> None:
        """Filtering by tag passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.contents.ContentRepository",
            return_value=mock_repo,
        ):
            resp = await contents_client.get("/api/v1/contents", params={"tag": "AI"})

        assert resp.status_code == 200
        mock_repo.list.assert_called_once()
        call_kwargs = mock_repo.list.call_args
        assert call_kwargs.kwargs.get("tag") == "AI" or ("AI" in str(call_kwargs))

    @pytest.mark.asyncio
    async def test_list_contents_filter_by_source_id(
        self, contents_client: AsyncClient
    ) -> None:
        """Filtering by source_id passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.contents.ContentRepository",
            return_value=mock_repo,
        ):
            resp = await contents_client.get(
                "/api/v1/contents", params={"source_id": str(SOURCE_ID)}
            )

        assert resp.status_code == 200
        mock_repo.list.assert_called_once()
        call_kwargs = mock_repo.list.call_args
        assert str(SOURCE_ID) in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_list_contents_filter_by_cluster_id(
        self, contents_client: AsyncClient
    ) -> None:
        """Filtering by cluster_id passes the parameter to the repository."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.contents.ContentRepository",
            return_value=mock_repo,
        ):
            resp = await contents_client.get(
                "/api/v1/contents", params={"cluster_id": str(CLUSTER_ID)}
            )

        assert resp.status_code == 200
        mock_repo.list.assert_called_once()
        call_kwargs = mock_repo.list.call_args
        assert str(CLUSTER_ID) in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_list_contents_limit_capped_at_100(
        self, contents_client: AsyncClient
    ) -> None:
        """Limit values above 100 should be capped or rejected."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.contents.ContentRepository",
            return_value=mock_repo,
        ):
            resp = await contents_client.get("/api/v1/contents", params={"limit": 200})

        # Either the router caps limit to 100 (200->OK) or rejects (422).
        if resp.status_code == 200:
            call_kwargs = mock_repo.list.call_args
            actual_limit = call_kwargs.kwargs.get(
                "limit", call_kwargs.args[0] if call_kwargs.args else None
            )
            assert actual_limit is not None and actual_limit <= 100


# ===========================================================================
# AC-T042-2: POST /api/v1/search -- hybrid search
# ===========================================================================


class TestSearchEndpoint:
    """AC-T042-2: POST /api/v1/search -- hybrid search endpoint."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, search_client: AsyncClient) -> None:
        """POST /api/v1/search with query returns search results."""
        mock_engine = AsyncMock()
        mock_engine.search.return_value = {
            "items": [_make_search_result()],
            "total": 1,
            "query_time_ms": 42,
        }

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            resp = await search_client.post(
                "/api/v1/search",
                json={"query": "artificial intelligence"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "query_time_ms" in body
        assert len(body["items"]) == 1
        assert "content_id" in body["items"][0]
        assert "title" in body["items"][0]
        assert "score" in body["items"][0]

    @pytest.mark.asyncio
    async def test_search_with_mode_and_filters(
        self, search_client: AsyncClient
    ) -> None:
        """Search with search_mode, tags, date_from, date_to passes params."""
        mock_engine = AsyncMock()
        mock_engine.search.return_value = {
            "items": [],
            "total": 0,
            "query_time_ms": 10,
        }

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            resp = await search_client.post(
                "/api/v1/search",
                json={
                    "query": "test query",
                    "search_mode": "semantic",
                    "tags": ["AI", "ML"],
                    "date_from": "2025-01-01T00:00:00Z",
                    "date_to": "2025-12-31T23:59:59Z",
                },
            )

        assert resp.status_code == 200
        mock_engine.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_empty_query_422(self, search_client: AsyncClient) -> None:
        """POST /api/v1/search without query returns 422."""
        resp = await search_client.post(
            "/api/v1/search",
            json={},
        )
        assert resp.status_code == 422


# ===========================================================================
# AC-T042-3: POST /api/v1/search/chat -- conversational search
# ===========================================================================


class TestChatSearchEndpoint:
    """AC-T042-3: POST /api/v1/search/chat -- instant Q&A."""

    @pytest.mark.asyncio
    async def test_chat_search_returns_response(
        self, search_client: AsyncClient
    ) -> None:
        """POST /api/v1/search/chat returns answer with sources."""
        mock_engine = AsyncMock()
        mock_engine.chat.return_value = {
            "session_id": "sess-001",
            "answer": "AI is a broad field...",
            "sources": [
                {
                    "content_id": str(CONTENT_ID),
                    "title": "AI Article",
                    "url": "https://example.com/ai",
                }
            ],
            "query_time_ms": 500,
        }

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            resp = await search_client.post(
                "/api/v1/search/chat",
                json={"message": "What is AI?"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert "answer" in body
        assert "sources" in body
        assert "query_time_ms" in body
        assert isinstance(body["sources"], list)

    @pytest.mark.asyncio
    async def test_chat_search_with_session_id(
        self, search_client: AsyncClient
    ) -> None:
        """Chat with existing session_id continues the conversation."""
        mock_engine = AsyncMock()
        mock_engine.chat.return_value = {
            "session_id": "sess-001",
            "answer": "Follow-up answer...",
            "sources": [],
            "query_time_ms": 300,
        }

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            resp = await search_client.post(
                "/api/v1/search/chat",
                json={
                    "message": "Tell me more",
                    "session_id": "sess-001",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "sess-001"

    @pytest.mark.asyncio
    async def test_chat_search_missing_query_422(
        self, search_client: AsyncClient
    ) -> None:
        """POST /api/v1/search/chat without message returns 422."""
        resp = await search_client.post(
            "/api/v1/search/chat",
            json={},
        )
        assert resp.status_code == 422


# ===========================================================================
# AC-T042-4: Subscription CRUD (/api/v1/subscriptions)
# ===========================================================================


class TestSubscriptionCRUD:
    """AC-T042-4: Subscription rules CRUD."""

    @pytest.mark.asyncio
    async def test_list_subscriptions(self, subscriptions_client: AsyncClient) -> None:
        """GET /api/v1/subscriptions returns paginated subscription list."""
        mock_repo = AsyncMock()
        mock_repo.list.return_value = {
            "items": [_make_subscription_obj()],
            "next_cursor": None,
            "has_more": False,
        }

        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionRepository",
            return_value=mock_repo,
        ):
            resp = await subscriptions_client.get("/api/v1/subscriptions")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "next_cursor" in body
        assert "has_more" in body
        assert isinstance(body["items"], list)
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert "id" in item
        assert "name" in item
        assert "channel" in item
        assert "status" in item

    @pytest.mark.asyncio
    async def test_create_subscription_201(
        self, subscriptions_client: AsyncClient
    ) -> None:
        """POST /api/v1/subscriptions creates a new subscription rule."""
        mock_repo = AsyncMock()
        created = _make_subscription_obj()
        mock_repo.create.return_value = created

        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionRepository",
            return_value=mock_repo,
        ):
            resp = await subscriptions_client.post(
                "/api/v1/subscriptions",
                json={
                    "name": "test-subscription",
                    "channel": "wechat",
                    "channel_config": {"openid": "test_openid"},
                    "match_rules": {"keywords": ["AI"]},
                },
            )

        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["name"] == "test-subscription"
        assert body["channel"] == "wechat"
        assert body["status"] == "active"
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_update_subscription(self, subscriptions_client: AsyncClient) -> None:
        """PATCH /api/v1/subscriptions/{id} partially updates subscription."""
        mock_repo = AsyncMock()
        updated = _make_subscription_obj(status="paused")
        mock_repo.update.return_value = updated

        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionRepository",
            return_value=mock_repo,
        ):
            resp = await subscriptions_client.patch(
                f"/api/v1/subscriptions/{SUB_ID}",
                json={"status": "paused"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "paused"

    @pytest.mark.asyncio
    async def test_delete_subscription_204(
        self, subscriptions_client: AsyncClient
    ) -> None:
        """DELETE /api/v1/subscriptions/{id} returns 204 on success."""
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = True

        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionRepository",
            return_value=mock_repo,
        ):
            resp = await subscriptions_client.delete(f"/api/v1/subscriptions/{SUB_ID}")

        assert resp.status_code == 204
        assert resp.content == b""

    @pytest.mark.asyncio
    async def test_delete_subscription_not_found_404(
        self, subscriptions_client: AsyncClient
    ) -> None:
        """DELETE non-existent subscription returns 404."""
        mock_repo = AsyncMock()
        mock_repo.delete.return_value = False

        nonexistent_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with patch(
            "intellisource.api.routers.subscriptions.SubscriptionRepository",
            return_value=mock_repo,
        ):
            resp = await subscriptions_client.delete(
                f"/api/v1/subscriptions/{nonexistent_id}"
            )

        assert resp.status_code == 404


# ===========================================================================
# AC-T042-5: GET /api/v1/llm/stats -- LLM usage statistics
# ===========================================================================


class TestLLMStatsEndpoint:
    """AC-T042-5: GET /api/v1/llm/stats -- LLM usage statistics."""

    @pytest.mark.asyncio
    async def test_llm_stats_returns_aggregated_data(
        self, llm_client: AsyncClient
    ) -> None:
        """GET /api/v1/llm/stats returns aggregated LLM usage statistics."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = {
            "period": "day",
            "total_calls": 150,
            "total_tokens": 50000,
            "total_input_tokens": 30000,
            "total_output_tokens": 20000,
            "avg_latency_ms": 320.5,
            "by_model": [
                {
                    "model": "gpt-4",
                    "calls": 100,
                    "tokens": 40000,
                    "avg_latency_ms": 400.0,
                    "error_rate": 0.02,
                }
            ],
            "by_date": [
                {
                    "date": "2025-06-01",
                    "calls": 150,
                    "tokens": 50000,
                }
            ],
        }

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert "period" in body
        assert "total_calls" in body
        assert "total_tokens" in body
        assert "total_input_tokens" in body
        assert "total_output_tokens" in body
        assert "avg_latency_ms" in body
        assert "by_model" in body
        assert "by_date" in body
        assert isinstance(body["by_model"], list)

    @pytest.mark.asyncio
    async def test_llm_stats_period_filter(self, llm_client: AsyncClient) -> None:
        """GET /api/v1/llm/stats with period filter returns 200."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = {
            "period": "month",
            "total_calls": 50,
            "total_tokens": 10000,
            "total_input_tokens": 6000,
            "total_output_tokens": 4000,
            "avg_latency_ms": 250.0,
            "by_model": [],
            "by_date": [],
        }

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get(
                "/api/v1/llm/stats",
                params={"period": "month"},
            )

        assert resp.status_code == 200
        mock_repo.get_stats.assert_called_once()
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("period") == "month"


# ===========================================================================
# AC-T042-6: GET /api/v1/health and GET /api/v1/metrics -- system endpoints
# ===========================================================================


class TestSystemEndpoints:
    """AC-T042-6: System health and metrics endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, system_client: AsyncClient) -> None:
        """GET /api/v1/health returns system health status."""
        with patch(
            "intellisource.api.routers.system.check_health",
            new_callable=AsyncMock,
            return_value={
                "status": "healthy",
                "version": "1.0.0",
                "uptime_seconds": 3600,
                "checks": {
                    "database": "healthy",
                    "redis": "healthy",
                    "celery": "healthy",
                },
                "timestamp": "2025-06-01T12:00:00+00:00",
            },
        ):
            resp = await system_client.get("/api/v1/health")

        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] in ("healthy", "degraded", "unhealthy")
        assert "version" in body
        assert "uptime_seconds" in body
        assert "checks" in body
        assert "database" in body["checks"]
        assert "redis" in body["checks"]
        assert "celery" in body["checks"]
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, system_client: AsyncClient) -> None:
        """GET /api/v1/metrics returns Prometheus-format text."""
        with patch(
            "intellisource.api.routers.system.get_metrics",
            new_callable=AsyncMock,
            return_value=(
                "# HELP is_collect_total Total collections\nis_collect_total 42\n"
            ),  # noqa: E501
        ):
            resp = await system_client.get("/api/v1/metrics")

        assert resp.status_code == 200
        # Prometheus metrics are text/plain
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "is_collect_total" in resp.text

    @pytest.mark.asyncio
    async def test_openapi_contains_all_paths(self, system_client: AsyncClient) -> None:
        """OpenAPI spec documents the system endpoints."""
        # Build a full app with all available routers to check OpenAPI completeness
        full_app = FastAPI()
        if not _SYSTEM_MISSING:
            full_app.include_router(system_router, prefix="/api/v1")
        if not _CONTENTS_MISSING:
            full_app.include_router(contents_router, prefix="/api/v1")
        if not _SEARCH_MISSING:
            full_app.include_router(search_router, prefix="/api/v1")
        if not _SUBSCRIPTIONS_MISSING:
            full_app.include_router(subscriptions_router, prefix="/api/v1")
        if not _LLM_MISSING:
            full_app.include_router(llm_router, prefix="/api/v1")

        transport = ASGITransport(app=full_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/openapi.json")

        assert resp.status_code == 200
        body = resp.json()
        paths = body.get("paths", {})

        # Verify key paths are documented
        assert "/api/v1/health" in paths, "GET /api/v1/health not in OpenAPI"
        assert "/api/v1/metrics" in paths, "GET /api/v1/metrics not in OpenAPI"
        assert "/api/v1/contents" in paths, "GET /api/v1/contents not in OpenAPI"
        assert "/api/v1/search" in paths, "POST /api/v1/search not in OpenAPI"
        assert "/api/v1/search/chat" in paths, "POST /api/v1/search/chat not in OpenAPI"
        assert "/api/v1/subscriptions" in paths, "Subscriptions not in OpenAPI"
        assert "/api/v1/llm/stats" in paths, "GET /api/v1/llm/stats not in OpenAPI"
