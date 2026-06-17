"""Tests for LLM statistics dashboard API.

Covers:
  AC-T060-1: GET /api/v1/llm/stats?period= supports day/week/month
  AC-T060-2: Response fields: period, total_calls, total_tokens,
             total_input_tokens, total_output_tokens
  AC-T060-3: Response field: avg_latency_ms (AVG(latency_ms) global)
  AC-T060-4: Response field: by_model[] (GROUP BY model) with
             model/call_count/input_tokens/output_tokens/error_rate
  AC-T060-5: Response field: by_date[] (GROUP BY DATE(created_at))
             with date/call_count/total_tokens
  AC-T060-6: No data returns empty aggregates (total_calls=0,
             by_model=[], by_date=[])
  AC-T060-7: Optional model and call_type filter parameters
  AC-T060-8: mypy --strict zero errors
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers.llm import router as llm_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FULL_STATS: dict[str, Any] = {
    "period": "day",
    "total_calls": 150,
    "total_tokens": 50000,
    "total_input_tokens": 30000,
    "total_output_tokens": 20000,
    "avg_latency_ms": 320.5,
    "by_model": [
        {
            "model": "gpt-4o-mini",
            "call_count": 100,
            "input_tokens": 25000,
            "output_tokens": 15000,
            "error_rate": 0.02,
        }
    ],
    "by_date": [
        {
            "date": "2025-06-01",
            "call_count": 150,
            "total_tokens": 50000,
        }
    ],
}

_EMPTY_STATS: dict[str, Any] = {
    "period": "day",
    "total_calls": 0,
    "total_tokens": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "avg_latency_ms": 0.0,
    "by_model": [],
    "by_date": [],
}


@pytest.fixture()
def llm_app() -> FastAPI:
    application = FastAPI()
    application.include_router(llm_router, prefix="/api/v1")
    return application


@pytest.fixture()
async def llm_client(llm_app: FastAPI) -> AsyncClient:  # type: ignore[misc]
    transport = ASGITransport(app=llm_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AC-T060-1: period parameter (day/week/month)
# ---------------------------------------------------------------------------


class TestPeriodParameter:
    """AC-T060-1: GET /api/v1/llm/stats supports period=day/week/month."""

    @pytest.mark.asyncio
    async def test_default_period_is_day(self, llm_client: AsyncClient) -> None:
        """Omitting period defaults to 'day'."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("period") == "day"

    @pytest.mark.asyncio
    async def test_period_week(self, llm_client: AsyncClient) -> None:
        """period=week is passed to repository."""
        mock_repo = AsyncMock()
        stats = dict(_FULL_STATS, period="week")
        mock_repo.get_stats.return_value = stats

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats", params={"period": "week"})

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("period") == "week"

    @pytest.mark.asyncio
    async def test_period_month(self, llm_client: AsyncClient) -> None:
        """period=month is passed to repository."""
        mock_repo = AsyncMock()
        stats = dict(_FULL_STATS, period="month")
        mock_repo.get_stats.return_value = stats

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats", params={"period": "month"})

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("period") == "month"


# ---------------------------------------------------------------------------
# invalid period returns 400
# ---------------------------------------------------------------------------


class TestInvalidPeriod:
    """Invalid period value returns HTTP 400, not 500."""

    @pytest.mark.asyncio
    async def test_invalid_period_returns_400(self, llm_client: AsyncClient) -> None:
        """period=invalid triggers ValueError in repo; router converts to HTTP 400."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.side_effect = ValueError(
            "Unsupported period: 'invalid'. Valid values: ['day', 'month', 'week']"
        )

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get(
                "/api/v1/llm/stats", params={"period": "invalid"}
            )

        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert "invalid" in body["error"]["message"]


# ---------------------------------------------------------------------------
# AC-T060-2 & AC-T060-3: Required top-level response fields
# ---------------------------------------------------------------------------


class TestResponseFields:
    """AC-T060-2 + AC-T060-3: Response contains all required fields."""

    @pytest.mark.asyncio
    async def test_response_contains_period(self, llm_client: AsyncClient) -> None:
        """Response contains 'period' field echoing the requested period."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert "period" in body
        assert body["period"] == "day"

    @pytest.mark.asyncio
    async def test_response_contains_token_fields(
        self, llm_client: AsyncClient
    ) -> None:
        """Response contains total_calls, total_tokens, total_input_tokens, total_output_tokens."""  # noqa: E501
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert "total_calls" in body
        assert "total_tokens" in body
        assert "total_input_tokens" in body
        assert "total_output_tokens" in body
        assert body["total_calls"] == 150
        assert body["total_tokens"] == 50000
        assert body["total_input_tokens"] == 30000
        assert body["total_output_tokens"] == 20000

    @pytest.mark.asyncio
    async def test_response_contains_avg_latency_ms(
        self, llm_client: AsyncClient
    ) -> None:
        """AC-T060-3: Response contains avg_latency_ms (global AVG aggregate)."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert "avg_latency_ms" in body
        assert body["avg_latency_ms"] == 320.5


# ---------------------------------------------------------------------------
# AC-T060-4: by_model[] with correct fields
# ---------------------------------------------------------------------------


class TestByModel:
    """AC-T060-4: by_model[] is grouped by model with required per-model fields."""

    @pytest.mark.asyncio
    async def test_by_model_present_and_list(self, llm_client: AsyncClient) -> None:
        """by_model field is present and is a list."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert "by_model" in body
        assert isinstance(body["by_model"], list)

    @pytest.mark.asyncio
    async def test_by_model_item_fields(self, llm_client: AsyncClient) -> None:
        """Each by_model item contains model, call_count, input_tokens, output_tokens, error_rate."""  # noqa: E501
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert len(body["by_model"]) == 1
        item = body["by_model"][0]
        assert item["model"] == "gpt-4o-mini"
        assert item["call_count"] == 100
        assert item["input_tokens"] == 25000
        assert item["output_tokens"] == 15000
        assert item["error_rate"] == 0.02


# ---------------------------------------------------------------------------
# AC-T060-5: by_date[] with correct fields
# ---------------------------------------------------------------------------


class TestByDate:
    """AC-T060-5: by_date[] is grouped by date with required per-date fields."""

    @pytest.mark.asyncio
    async def test_by_date_present_and_list(self, llm_client: AsyncClient) -> None:
        """by_date field is present and is a list."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert "by_date" in body
        assert isinstance(body["by_date"], list)

    @pytest.mark.asyncio
    async def test_by_date_item_fields(self, llm_client: AsyncClient) -> None:
        """Each by_date item contains date, call_count, total_tokens."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        body = resp.json()
        assert len(body["by_date"]) == 1
        item = body["by_date"][0]
        assert item["date"] == "2025-06-01"
        assert item["call_count"] == 150
        assert item["total_tokens"] == 50000


# ---------------------------------------------------------------------------
# AC-T060-6: Empty data returns zero aggregates (no error)
# ---------------------------------------------------------------------------


class TestEmptyData:
    """AC-T060-6: No data returns empty aggregates without error."""

    @pytest.mark.asyncio
    async def test_empty_data_returns_zeros(self, llm_client: AsyncClient) -> None:
        """When no data exists, response has total_calls=0, by_model=[], by_date=[]."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _EMPTY_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get("/api/v1/llm/stats")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_calls"] == 0
        assert body["total_tokens"] == 0
        assert body["by_model"] == []
        assert body["by_date"] == []


# ---------------------------------------------------------------------------
# AC-T060-7: Optional model and call_type filter parameters
# ---------------------------------------------------------------------------


class TestFilterParameters:
    """AC-T060-7: model and call_type optional filter parameters."""

    @pytest.mark.asyncio
    async def test_model_filter_passed_to_repo(self, llm_client: AsyncClient) -> None:
        """model query param is forwarded to repository.get_stats()."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get(
                "/api/v1/llm/stats", params={"model": "gpt-4o-mini"}
            )

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("model") == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_call_type_filter_passed_to_repo(
        self, llm_client: AsyncClient
    ) -> None:
        """call_type query param is forwarded to repository.get_stats()."""
        mock_repo = AsyncMock()
        mock_repo.get_stats.return_value = _FULL_STATS

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get(
                "/api/v1/llm/stats",
                params={"call_type": "structured_extraction"},
            )

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("call_type") == "structured_extraction"

    @pytest.mark.asyncio
    async def test_combined_filters_passed_to_repo(
        self, llm_client: AsyncClient
    ) -> None:
        """period + model + call_type are all forwarded to repository.get_stats()."""
        mock_repo = AsyncMock()
        stats = dict(_FULL_STATS, period="week")
        mock_repo.get_stats.return_value = stats

        with patch(
            "intellisource.api.routers.llm.LLMCallLogRepository",
            return_value=mock_repo,
        ):
            resp = await llm_client.get(
                "/api/v1/llm/stats",
                params={
                    "period": "week",
                    "model": "claude-3-haiku",
                    "call_type": "summary_generation",
                },
            )

        assert resp.status_code == 200
        call_kwargs = mock_repo.get_stats.call_args
        assert call_kwargs.kwargs.get("period") == "week"
        assert call_kwargs.kwargs.get("model") == "claude-3-haiku"
        assert call_kwargs.kwargs.get("call_type") == "summary_generation"
