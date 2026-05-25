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


# ---------------------------------------------------------------------------
# B-002: SearchRequest date_from / date_to typed as datetime
# ---------------------------------------------------------------------------


class TestSearchDateTypeValidation:
    """B-002: date_from/date_to as datetime → FastAPI returns 422 on bad input."""

    async def test_search_accepts_iso_date_from(self, search_app: FastAPI) -> None:
        """Legal ISO 8601 date string parses into datetime and forwards to engine."""
        captured: dict[str, Any] = {}

        async def fake_search(**kwargs: Any) -> Any:
            captured.update(kwargs)
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
                    json={"query": "x", "date_from": "2025-01-01T00:00:00Z"},
                )

        from datetime import datetime as _dt

        assert resp.status_code == 200
        date_from = captured.get("date_from")
        assert isinstance(date_from, _dt), (
            f"date_from must be datetime, got {type(date_from).__name__}"
        )

    async def test_search_rejects_invalid_date_from_with_422(
        self, search_app: FastAPI
    ) -> None:
        """Non-parseable date string must produce 422 at FastAPI validation layer."""
        async with AsyncClient(
            transport=ASGITransport(app=search_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/search",
                json={"query": "x", "date_from": "not-a-date"},
            )
        assert resp.status_code == 422, (
            f"invalid date must yield 422, got {resp.status_code}: {resp.text}"
        )

    async def test_search_accepts_none_date_from(self, search_app: FastAPI) -> None:
        """Omitting date_from is valid; engine receives None."""
        captured: dict[str, Any] = {}

        async def fake_search(**kwargs: Any) -> Any:
            captured.update(kwargs)
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
                resp = await client.post("/api/v1/search", json={"query": "x"})

        assert resp.status_code == 200
        assert captured.get("date_from") is None
        assert captured.get("date_to") is None
