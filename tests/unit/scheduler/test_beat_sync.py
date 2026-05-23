"""Unit tests for scheduler.beat_sync (AC-T100-1/6)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from celery.schedules import crontab


def _make_celery_stub() -> Any:
    """Return a stub celery_app exposing a settable ``conf.beat_schedule``."""

    class _Conf:
        beat_schedule: dict[str, dict[str, Any]] = {}

    return SimpleNamespace(conf=_Conf())


class TestSyncBeatSchedules:
    """AC-T100-1: sync_beat_schedules projects SchedulerManager onto conf."""

    def test_integer_seconds_becomes_timedelta(self) -> None:
        from intellisource.scheduler.beat_sync import sync_beat_schedules
        from intellisource.scheduler.state_machine import SchedulerManager

        sm = SchedulerManager()
        sm.register_schedule(
            name="src-1",
            cron_expr="600",
            pipeline_name="scheduled-collect",
            params={"source_id": "src-1"},
        )
        celery_app = _make_celery_stub()
        result = sync_beat_schedules(celery_app, sm)

        entry = result["src-1"]
        assert entry["task"] == "run_pipeline"
        assert isinstance(entry["schedule"], timedelta)
        assert entry["schedule"] == timedelta(seconds=600)
        assert entry["kwargs"] == {
            "pipeline_name": "scheduled-collect",
            "params": {"source_id": "src-1"},
        }

    def test_cron_string_becomes_crontab(self) -> None:
        from intellisource.scheduler.beat_sync import sync_beat_schedules
        from intellisource.scheduler.state_machine import SchedulerManager

        sm = SchedulerManager()
        sm.register_schedule(
            name="src-2",
            cron_expr="*/5 * * * *",
            pipeline_name="content-process",
            params={},
        )
        celery_app = _make_celery_stub()
        result = sync_beat_schedules(celery_app, sm)

        assert isinstance(result["src-2"]["schedule"], crontab)

    def test_empty_scheduler_writes_empty_dict(self) -> None:
        from intellisource.scheduler.beat_sync import sync_beat_schedules
        from intellisource.scheduler.state_machine import SchedulerManager

        sm = SchedulerManager()
        celery_app = _make_celery_stub()

        result = sync_beat_schedules(celery_app, sm)

        assert result == {}
        assert celery_app.conf.beat_schedule == {}

    def test_unparseable_expr_is_skipped_with_warning(self, caplog: Any) -> None:
        from intellisource.scheduler.beat_sync import sync_beat_schedules
        from intellisource.scheduler.state_machine import SchedulerManager

        sm = SchedulerManager()
        sm.register_schedule(
            name="bad",
            cron_expr="not-a-cron",
            pipeline_name="x",
            params={},
        )
        celery_app = _make_celery_stub()
        with caplog.at_level("WARNING"):
            result = sync_beat_schedules(celery_app, sm)

        assert "bad" not in result
        assert any("unparseable" in r.message.lower() for r in caplog.records)

    def test_writes_to_celery_conf_beat_schedule(self) -> None:
        from intellisource.scheduler.beat_sync import sync_beat_schedules
        from intellisource.scheduler.state_machine import SchedulerManager

        sm = SchedulerManager()
        sm.register_schedule(
            name="x",
            cron_expr="60",
            pipeline_name="p",
            params={},
        )
        celery_app = _make_celery_stub()
        sync_beat_schedules(celery_app, sm)

        assert "x" in celery_app.conf.beat_schedule
        assert celery_app.conf.beat_schedule["x"]["task"] == "run_pipeline"


class TestParseSchedule:
    """Internal _parse_schedule edge cases."""

    def test_negative_seconds_rejected(self) -> None:
        from intellisource.scheduler.beat_sync import _parse_schedule

        with pytest.raises(ValueError, match="must be > 0"):
            _parse_schedule("-30")

    def test_zero_seconds_rejected(self) -> None:
        from intellisource.scheduler.beat_sync import _parse_schedule

        with pytest.raises(ValueError, match="must be > 0"):
            _parse_schedule("0")

    def test_three_field_cron_rejected(self) -> None:
        from intellisource.scheduler.beat_sync import _parse_schedule

        with pytest.raises(ValueError, match="5-field cron"):
            _parse_schedule("* * *")
