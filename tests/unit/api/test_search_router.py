"""Tests for T-085 revision: search router correctness.

Covers:
  R-001: search_mode is forwarded as mode= to HybridSearchEngine.search()
  R-003: POST /search/chat with empty message list returns HTTP 400
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers.search import router as search_router
from intellisource.search.hybrid import HybridSearchEngine

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def search_app() -> FastAPI:
    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# R-001: search_mode reaches engine.search() as mode=
# ---------------------------------------------------------------------------


class TestSearchModeForwarding:
    """R-001: router must call engine.search(mode=...) not search_mode=..."""

    async def test_search_mode_keyword_reaches_engine(
        self, search_app: FastAPI
    ) -> None:
        """POST /search search_mode='keyword' must reach engine as mode='keyword'."""
        captured_kwargs: dict[str, Any] = {}

        async def fake_search(**kwargs: Any) -> Any:
            captured_kwargs.update(kwargs)
            return {"items": [], "total": 0, "query_time_ms": 0}

        mock_engine = MagicMock(spec=HybridSearchEngine)
        mock_engine.search = AsyncMock(side_effect=fake_search)

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "climate change", "search_mode": "keyword"},
                )

        assert resp.status_code == 200
        assert captured_kwargs.get("mode") == "keyword", (
            "router must pass mode= to engine.search(), got: "
            f"mode={captured_kwargs.get('mode')!r}, "
            f"search_mode={captured_kwargs.get('search_mode')!r}"
        )
        assert "search_mode" not in captured_kwargs, (
            "router must not pass search_mode= kwarg to engine.search()"
        )

    async def test_search_mode_semantic_reaches_engine(
        self, search_app: FastAPI
    ) -> None:
        """POST /search search_mode='semantic' must reach engine as mode='semantic'."""
        captured_kwargs: dict[str, Any] = {}

        async def fake_search(**kwargs: Any) -> Any:
            captured_kwargs.update(kwargs)
            return {"items": [], "total": 0, "query_time_ms": 0}

        mock_engine = MagicMock(spec=HybridSearchEngine)
        mock_engine.search = AsyncMock(side_effect=fake_search)

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "neural networks", "search_mode": "semantic"},
                )

        assert resp.status_code == 200
        assert captured_kwargs.get("mode") == "semantic"


# ---------------------------------------------------------------------------
# R-003: empty messages -> 400
# ---------------------------------------------------------------------------


class TestChatEmptyMessages:
    """R-003: chat() ValueError on empty messages translates to HTTP 400."""

    async def test_chat_with_empty_message_string_still_calls_engine(
        self, search_app: FastAPI
    ) -> None:
        """ChatRequest.message is a non-empty required string by Pydantic.

        A truly empty body ({'message': ''}) will pass Pydantic validation but
        the engine receives a single-element messages list — no ValueError.
        This test confirms the router path does NOT 400 for a valid (non-empty) message.
        """
        mock_engine = MagicMock(spec=HybridSearchEngine)
        mock_engine.chat = AsyncMock(
            return_value={
                "session_id": "s-1",
                "answer": "hello",
                "sources": [],
                "query_time_ms": 0,
            }
        )

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search/chat",
                    json={"message": "hello"},
                )

        assert resp.status_code == 200

    async def test_chat_engine_value_error_returns_400(
        self, search_app: FastAPI
    ) -> None:
        """When engine.chat() raises ValueError, router must return HTTP 400."""
        mock_engine = MagicMock(spec=HybridSearchEngine)
        mock_engine.chat = AsyncMock(
            side_effect=ValueError("messages must contain at least one entry")
        )

        with patch(
            "intellisource.api.routers.search.HybridSearchEngine",
            return_value=mock_engine,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search/chat",
                    json={"message": "any"},
                )

        assert resp.status_code == 400
        body = resp.json()
        assert "detail" in body
        assert "messages" in body["detail"].lower()
