"""Tests for search router correctness.

Covers:
  R-001: search_mode is forwarded as mode= to HybridSearchEngine.search()
  T-EMB-2 AC-7: gateway from app.state is passed to HybridSearchEngine
  T-EMB-2 R-003: HTTP semantic request triggers gateway.embed via router→engine chain
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.deps import get_db_session
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


# ---------------------------------------------------------------------------
# T-EMB-2 AC-7: /search endpoint injects llm_gateway from app.state
# ---------------------------------------------------------------------------


class TestSearchEndpointGatewayWiring:
    """AC-7: POST /search constructs HybridSearchEngine with gateway from app.state."""

    async def test_gateway_present_in_app_state_is_passed_to_engine(
        self, search_app: FastAPI
    ) -> None:
        """app.state.llm_gateway set → engine constructed with that gateway."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from intellisource.api.routers.search import router as _router  # noqa: F401

        fake_gateway = MagicMock()
        search_app.state.llm_gateway = fake_gateway

        constructed_kwargs: dict = {}
        original_init = None

        def capturing_init(self, session, **kwargs):  # type: ignore[no-untyped-def]
            constructed_kwargs.update(kwargs)
            # call real __init__ so search() works
            original_init(self, session, **kwargs)  # type: ignore[misc]

        from intellisource.search.hybrid import HybridSearchEngine

        original_init = HybridSearchEngine.__init__

        mock_engine_search = AsyncMock(
            return_value={"items": [], "total": 0, "query_time_ms": 0}
        )

        with (
            patch.object(HybridSearchEngine, "__init__", capturing_init),
            patch.object(HybridSearchEngine, "search", mock_engine_search),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "semantic test", "search_mode": "semantic"},
                )

        assert resp.status_code == 200
        assert constructed_kwargs.get("llm_gateway") is fake_gateway, (
            "engine must be constructed with llm_gateway=app.state.llm_gateway; "
            f"got llm_gateway={constructed_kwargs.get('llm_gateway')!r}"
        )

    async def test_missing_gateway_in_app_state_uses_none(
        self, search_app: FastAPI
    ) -> None:
        """When app.state has no llm_gateway, engine is constructed with None."""
        from unittest.mock import AsyncMock, patch

        from intellisource.search.hybrid import HybridSearchEngine

        # Ensure llm_gateway is absent
        if hasattr(search_app.state, "llm_gateway"):
            del search_app.state.llm_gateway

        constructed_kwargs: dict = {}
        original_init = HybridSearchEngine.__init__

        def capturing_init(self, session, **kwargs):  # type: ignore[no-untyped-def]
            constructed_kwargs.update(kwargs)
            original_init(self, session, **kwargs)  # type: ignore[misc]

        mock_engine_search = AsyncMock(
            return_value={"items": [], "total": 0, "query_time_ms": 0}
        )

        with (
            patch.object(HybridSearchEngine, "__init__", capturing_init),
            patch.object(HybridSearchEngine, "search", mock_engine_search),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=search_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/search",
                    json={"query": "keyword only", "search_mode": "keyword"},
                )

        assert resp.status_code == 200, (
            f"endpoint must not crash when gateway is absent, got {resp.status_code}"
        )
        assert constructed_kwargs.get("llm_gateway") is None, (
            "engine must receive llm_gateway=None when app.state has no llm_gateway"
        )


# ---------------------------------------------------------------------------
# T-EMB-2 R-003: HTTP → engine → embed end-to-end wiring
# (no HybridSearchEngine.search patch)
# ---------------------------------------------------------------------------


def _make_fake_db_session() -> AsyncMock:
    """Return an AsyncMock that satisfies AsyncSession usage in HybridIndex."""
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    return session


class TestSemanticEmbedEndToEndWiring:
    """R-003: router→engine→embed chain is exercised without patching engine.search."""

    async def test_semantic_request_triggers_gateway_embed_exactly_once(
        self, search_app: FastAPI
    ) -> None:
        """semantic search_mode must cause gateway.embed to be called once via the
        full router→HybridSearchEngine→embed path; only HybridIndex.search is patched
        to avoid a real DB round-trip."""
        from intellisource.storage.vector import HybridIndex

        fake_vector = [0.01 * (i % 100) for i in range(1024)]
        fake_gateway = AsyncMock()
        fake_gateway.embed = AsyncMock(return_value=fake_vector)

        search_app.state.llm_gateway = fake_gateway

        fake_session = _make_fake_db_session()

        async def override_db_session() -> Any:
            yield fake_session

        search_app.dependency_overrides[get_db_session] = override_db_session

        try:
            with patch.object(HybridIndex, "search", AsyncMock(return_value=[])):
                async with AsyncClient(
                    transport=ASGITransport(app=search_app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/api/v1/search",
                        json={
                            "query": "semantic wiring test",
                            "search_mode": "semantic",
                        },
                    )
        finally:
            search_app.dependency_overrides.pop(get_db_session, None)

        assert resp.status_code == 200, (
            f"semantic request must return 200, got {resp.status_code}: {resp.text}"
        )
        fake_gateway.embed.assert_called_once_with("semantic wiring test")
