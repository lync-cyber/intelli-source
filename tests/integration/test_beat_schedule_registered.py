"""Integration test for AC-T100-2: worker_init populates conf.beat_schedule."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock


class TestBootstrapBeatSchedule:
    """`_bootstrap_beat_schedule` reads Source rows and projects them onto Beat."""

    def test_sources_populate_beat_schedule(self) -> None:
        from intellisource.scheduler import boot as boot_mod

        source_rows = [
            SimpleNamespace(
                id="11111111-1111-1111-1111-111111111111",
                type="rss",
                schedule_interval=600,
            ),
            SimpleNamespace(
                id="22222222-2222-2222-2222-222222222222",
                type="api",
                schedule_interval=300,
            ),
        ]

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = source_rows

        session = MagicMock()
        session.execute = AsyncMock(return_value=execute_result)

        @asynccontextmanager
        async def _factory_cm() -> Any:
            yield session

        def factory() -> Any:
            return _factory_cm()

        celery_stub = SimpleNamespace(conf=SimpleNamespace(beat_schedule={}))

        # Patch the module-level Celery singleton so _bootstrap_beat_schedule
        # writes to the stub instead of the real broker-bound app.
        original = boot_mod._module_celery_app
        boot_mod._module_celery_app = celery_stub  # type: ignore[assignment]
        try:
            boot_mod._bootstrap_beat_schedule(factory)
        finally:
            boot_mod._module_celery_app = original  # type: ignore[assignment]

        beat_schedule = celery_stub.conf.beat_schedule
        # Source rows project onto one run_pipeline entry each.
        source_entries = {
            k: v for k, v in beat_schedule.items() if v["task"] == "run_pipeline"
        }
        assert len(source_entries) == 2, (
            f"expected 2 source-derived entries, got {beat_schedule}"
        )
        for entry in source_entries.values():
            assert "pipeline_name" in entry["kwargs"]
        # The periodic-digest assembler is a static system task, always scheduled
        # alongside the DB-projected source pipelines.
        assert "assemble_daily_weekly_digests" in beat_schedule
        assert (
            beat_schedule["assemble_daily_weekly_digests"]["task"]
            == "assemble_daily_weekly_digests"
        )
        assert "cleanup_chat_sessions" in beat_schedule
        assert beat_schedule["cleanup_chat_sessions"]["task"] == "cleanup_chat_sessions"

    def test_empty_sources_table_logs_warning(self) -> None:
        from structlog.testing import capture_logs

        from intellisource.scheduler import boot as boot_mod

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []

        session = MagicMock()
        session.execute = AsyncMock(return_value=execute_result)

        @asynccontextmanager
        async def _factory_cm() -> Any:
            yield session

        def factory() -> Any:
            return _factory_cm()

        celery_stub = SimpleNamespace(conf=SimpleNamespace(beat_schedule={}))

        original = boot_mod._module_celery_app
        boot_mod._module_celery_app = celery_stub  # type: ignore[assignment]
        try:
            with capture_logs() as logs:
                boot_mod._bootstrap_beat_schedule(factory)
        finally:
            boot_mod._module_celery_app = original  # type: ignore[assignment]

        # No source rows → no run_pipeline entries, but the static periodic-digest
        # task is still scheduled.
        beat_schedule = celery_stub.conf.beat_schedule
        assert all(v["task"] != "run_pipeline" for v in beat_schedule.values())
        assert "assemble_daily_weekly_digests" in beat_schedule
        assert "cleanup_chat_sessions" in beat_schedule
        warnings = [e["event"] for e in logs]
        assert any("zero scheduled tasks" in w or "empty" in w for w in warnings)

    def test_is_beat_disabled_env_skips_sync(self, monkeypatch: Any) -> None:
        from intellisource.scheduler import boot as boot_mod

        monkeypatch.setenv("IS_BEAT_DISABLED", "1")
        celery_stub = SimpleNamespace(conf=SimpleNamespace(beat_schedule={}))

        original = boot_mod._module_celery_app
        boot_mod._module_celery_app = celery_stub  # type: ignore[assignment]
        try:
            boot_mod._bootstrap_beat_schedule(lambda: None)  # type: ignore[arg-type]
        finally:
            boot_mod._module_celery_app = original  # type: ignore[assignment]

        # When disabled, beat_schedule stays untouched (empty in this case).
        assert celery_stub.conf.beat_schedule == {}
