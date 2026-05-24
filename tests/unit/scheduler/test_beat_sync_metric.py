"""Tests for Beat sync failure metric and hard-fail option (F-37)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> None:
    """Reset MetricsCollector singleton state between tests."""
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


def _run_bootstrap(env: dict[str, str] | None = None) -> None:
    """Run _bootstrap_beat_schedule with a loop that raises ValueError."""
    from intellisource.scheduler import boot  # noqa: PLC0415

    factory = MagicMock()

    with patch.dict(os.environ, env or {}, clear=False):
        with patch("asyncio.new_event_loop") as mock_new_loop:
            mock_loop = MagicMock()
            mock_new_loop.return_value = mock_loop
            mock_loop.run_until_complete.side_effect = ValueError("DB down")
            boot._bootstrap_beat_schedule(factory)


class TestBeatSyncMetric:
    def test_beat_sync_failure_increments_counter(self) -> None:
        mc = MetricsCollector.get_instance()
        _run_bootstrap()
        assert mc.get_counter_value("scheduler_beat_sync_failed_total") == 1.0

    def test_counter_auto_registers_if_not_present(self) -> None:
        mc = MetricsCollector.get_instance()
        assert "scheduler_beat_sync_failed_total" not in mc._counters
        _run_bootstrap()
        assert mc._counters["scheduler_beat_sync_failed_total"] == 1.0

    def test_hard_fail_env_var_true_raises(self) -> None:
        from intellisource.scheduler import boot  # noqa: PLC0415

        factory = MagicMock()
        with patch.dict(os.environ, {"IS_BEAT_SYNC_HARD_FAIL": "true"}, clear=False):
            with patch("asyncio.new_event_loop") as mock_new_loop:
                mock_loop = MagicMock()
                mock_new_loop.return_value = mock_loop
                mock_loop.run_until_complete.side_effect = ValueError("DB down")
                with pytest.raises(ValueError, match="DB down"):
                    boot._bootstrap_beat_schedule(factory)

    def test_hard_fail_env_var_false_does_not_raise(self) -> None:
        _run_bootstrap(env={"IS_BEAT_SYNC_HARD_FAIL": "false"})

    def test_hard_fail_env_var_empty_does_not_raise(self) -> None:
        _run_bootstrap(env={"IS_BEAT_SYNC_HARD_FAIL": ""})

    def test_multiple_failures_accumulate_counter(self) -> None:
        mc = MetricsCollector.get_instance()
        _run_bootstrap()
        _run_bootstrap()
        assert mc.get_counter_value("scheduler_beat_sync_failed_total") == 2.0
