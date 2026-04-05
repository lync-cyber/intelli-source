"""Tests for CostTracker LLM call logging and aggregation.

Covers:
- AC-033: Each LLM call records model/input_tokens/output_tokens/latency_ms/
  input_length/output_length
- AC-T021-2: CostTracker supports aggregation by day/week/month
- AC-T021-3: CostTracker data persists to LLMCallLog table (E-007)
- AC-T021-4: Support querying statistics by model/call_type dimensions
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from intellisource.llm.cost_tracker import CostTracker, LLMCallRecord

from intellisource.storage.models import LLMCallLog

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(**overrides: Any) -> LLMCallRecord:
    """Build a sample LLMCallRecord with sensible defaults."""
    defaults: dict[str, Any] = {
        "model": "gpt-4o-mini",
        "provider": "openai",
        "call_type": "structured_extraction",
        "input_tokens": 150,
        "output_tokens": 80,
        "latency_ms": 320,
        "input_length": 1200,
        "output_length": 500,
        "status": "success",
    }
    defaults.update(overrides)
    return LLMCallRecord(**defaults)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def tracker(mock_session: AsyncMock) -> CostTracker:
    """Create a CostTracker wired to the mock session."""
    return CostTracker(session=mock_session)


# ===================================================================
# AC-033: Each LLM call records required fields
# ===================================================================


class TestCallRecording:
    """Verify every LLM call captures the required telemetry fields."""

    def test_llm_call_record_contains_model(self) -> None:
        """LLMCallRecord stores the model name."""
        record = _make_record(model="claude-3-haiku")
        assert record.model == "claude-3-haiku"

    def test_llm_call_record_contains_input_tokens(self) -> None:
        """LLMCallRecord stores input_tokens as an integer."""
        record = _make_record(input_tokens=250)
        assert record.input_tokens == 250
        assert isinstance(record.input_tokens, int)

    def test_llm_call_record_contains_output_tokens(self) -> None:
        """LLMCallRecord stores output_tokens as an integer."""
        record = _make_record(output_tokens=100)
        assert record.output_tokens == 100

    def test_llm_call_record_contains_latency_ms(self) -> None:
        """LLMCallRecord stores latency_ms."""
        record = _make_record(latency_ms=450)
        assert record.latency_ms == 450

    def test_llm_call_record_contains_input_length(self) -> None:
        """LLMCallRecord stores input_length (character count)."""
        record = _make_record(input_length=2000)
        assert record.input_length == 2000

    def test_llm_call_record_contains_output_length(self) -> None:
        """LLMCallRecord stores output_length (character count)."""
        record = _make_record(output_length=800)
        assert record.output_length == 800

    def test_llm_call_record_contains_all_required_fields(self) -> None:
        """LLMCallRecord exposes every field mandated by AC-033."""
        record = _make_record()
        required_fields = {
            "model",
            "input_tokens",
            "output_tokens",
            "latency_ms",
            "input_length",
            "output_length",
        }
        for field_name in required_fields:
            assert hasattr(record, field_name), f"Missing field: {field_name}"


# ===================================================================
# AC-T021-3: Persist to LLMCallLog table (E-007)
# ===================================================================


class TestPersistence:
    """Verify CostTracker persists call records to the database."""

    @pytest.mark.asyncio
    async def test_log_call_adds_to_session(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """log_call() adds an LLMCallLog ORM instance to the session."""
        record = _make_record()
        await tracker.log_call(record)

        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, LLMCallLog)

    @pytest.mark.asyncio
    async def test_log_call_commits_session(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """log_call() commits the session after adding the record."""
        record = _make_record()
        await tracker.log_call(record)

        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_call_maps_all_fields_to_orm(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """log_call() correctly maps LLMCallRecord fields to LLMCallLog columns."""
        record = _make_record(
            model="claude-3-haiku",
            provider="anthropic",
            call_type="summary_generation",
            input_tokens=300,
            output_tokens=150,
            latency_ms=500,
            input_length=2500,
            output_length=1000,
            status="success",
        )
        await tracker.log_call(record)

        orm_obj = mock_session.add.call_args[0][0]
        assert orm_obj.model == "claude-3-haiku"
        assert orm_obj.provider == "anthropic"
        assert orm_obj.call_type == "summary_generation"
        assert orm_obj.input_tokens == 300
        assert orm_obj.output_tokens == 150
        assert orm_obj.latency_ms == 500
        assert orm_obj.input_length == 2500
        assert orm_obj.output_length == 1000
        assert orm_obj.status == "success"

    @pytest.mark.asyncio
    async def test_log_call_persists_failed_status(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """log_call() correctly persists records with status=failed."""
        record = _make_record(status="failed")
        await tracker.log_call(record)

        orm_obj = mock_session.add.call_args[0][0]
        assert orm_obj.status == "failed"


# ===================================================================
# AC-T021-2: Aggregation by day/week/month
# ===================================================================


class TestAggregation:
    """Verify CostTracker supports time-based aggregation of call statistics."""

    @pytest.mark.asyncio
    async def test_aggregate_by_day_returns_daily_stats(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats(period='day') returns aggregated statistics for today."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=10,
                total_input_tokens=1500,
                total_output_tokens=800,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="day")

        assert stats["total_calls"] == 10
        assert stats["total_input_tokens"] == 1500
        assert stats["total_output_tokens"] == 800

    @pytest.mark.asyncio
    async def test_aggregate_by_week_returns_weekly_stats(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats(period='week') returns aggregated statistics for this week."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=70,
                total_input_tokens=10500,
                total_output_tokens=5600,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="week")

        assert stats["total_calls"] == 70
        assert stats["total_input_tokens"] == 10500

    @pytest.mark.asyncio
    async def test_aggregate_by_month_returns_monthly_stats(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats(period='month') returns aggregated statistics for this month."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=300,
                total_input_tokens=45000,
                total_output_tokens=24000,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="month")

        assert stats["total_calls"] == 300
        assert stats["total_input_tokens"] == 45000

    @pytest.mark.asyncio
    async def test_aggregate_invalid_period_raises_error(
        self, tracker: CostTracker
    ) -> None:
        """get_stats() with an unsupported period raises ValueError."""
        with pytest.raises(ValueError, match="period"):
            await tracker.get_stats(period="quarter")


# ===================================================================
# AC-T021-4: Query by model/call_type dimensions
# ===================================================================


class TestDimensionQuery:
    """Verify CostTracker supports filtering statistics by model and call_type."""

    @pytest.mark.asyncio
    async def test_stats_filtered_by_model(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats(model='gpt-4o-mini') returns stats only for that model."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=5,
                total_input_tokens=750,
                total_output_tokens=400,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="day", model="gpt-4o-mini")

        assert stats["total_calls"] == 5
        # Verify the query was executed (session.execute was called)
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stats_filtered_by_call_type(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats(call_type='structured_extraction') filters by call_type."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=8,
                total_input_tokens=1200,
                total_output_tokens=640,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="day", call_type="structured_extraction")

        assert stats["total_calls"] == 8
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stats_filtered_by_model_and_call_type(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats() supports combined model + call_type filtering."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(
                total_calls=3,
                total_input_tokens=450,
                total_output_tokens=240,
            )
        ]
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(
            period="week",
            model="claude-3-haiku",
            call_type="summary_generation",
        )

        assert stats["total_calls"] == 3
        assert stats["total_output_tokens"] == 240

    @pytest.mark.asyncio
    async def test_stats_with_no_matching_data_returns_zeros(
        self, tracker: CostTracker, mock_session: AsyncMock
    ) -> None:
        """get_stats() returns zero counts when no records match the filters."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute.return_value = mock_result

        stats = await tracker.get_stats(period="day", model="nonexistent-model")

        assert stats["total_calls"] == 0
        assert stats["total_input_tokens"] == 0
        assert stats["total_output_tokens"] == 0
