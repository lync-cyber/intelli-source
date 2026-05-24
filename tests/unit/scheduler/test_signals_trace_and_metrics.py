"""Tests for F-22 Celery signal metrics + F-23 trace_id propagation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.observability.metrics import MetricsCollector
from intellisource.observability.trace_context import (
    TRACE_HEADER_KEY,
    current_trace_id,
)


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> None:
    """Drop MetricsCollector singleton state between tests."""
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


def _make_task(headers: dict[str, Any] | None = None) -> SimpleNamespace:
    """Build a fake Celery task object with a settable .request namespace."""
    request = SimpleNamespace(headers=dict(headers or {}))
    return SimpleNamespace(request=request)


class TestTracePrerunRestoresContext:
    """F-23: task_prerun handler must read header trace_id and bind contextvar."""

    def test_trace_id_from_headers_binds_contextvar(self) -> None:
        from intellisource.scheduler.signals import _on_task_prerun

        task = _make_task(headers={TRACE_HEADER_KEY: "trace-abc-123"})
        _on_task_prerun(sender=task, task_id="celery-task-1")

        assert current_trace_id() == "trace-abc-123"

    def test_missing_trace_id_binds_empty_string(self) -> None:
        from intellisource.scheduler.signals import _on_task_prerun

        task = _make_task(headers={})
        _on_task_prerun(sender=task, task_id="celery-task-2")

        # Must not raise; empty value is the explicit fallback
        assert current_trace_id() == ""


class TestTracePostrunResetsContext:
    """F-23: task_postrun must reset contextvar so workers don't leak trace ids."""

    def test_postrun_resets_trace_id(self) -> None:
        from intellisource.scheduler.signals import (
            _on_task_postrun,
            _on_task_prerun,
        )

        task = _make_task(headers={TRACE_HEADER_KEY: "trace-postrun"})
        _on_task_prerun(sender=task, task_id="t1")
        assert current_trace_id() == "trace-postrun"

        _on_task_postrun(sender=task, task_id="t1", state="SUCCESS")
        # After reset the contextvar returns to the default ""
        assert current_trace_id() == ""


class TestPostrunMetrics:
    """F-22: postrun increments tasks_total and observes duration histogram."""

    def test_postrun_increments_total_counter(self) -> None:
        from intellisource.scheduler.signals import (
            _on_task_postrun,
            _on_task_prerun,
        )

        task = _make_task()
        _on_task_prerun(sender=task, task_id="t-1")
        _on_task_postrun(sender=task, task_id="t-1", state="SUCCESS")

        mc = MetricsCollector.get_instance()
        assert mc.get_counter_value("celery_tasks_total") == 1.0

    def test_postrun_records_duration_histogram(self) -> None:
        from intellisource.scheduler.signals import (
            _on_task_postrun,
            _on_task_prerun,
        )

        task = _make_task()
        _on_task_prerun(sender=task, task_id="t-2")
        _on_task_postrun(sender=task, task_id="t-2", state="SUCCESS")

        mc = MetricsCollector.get_instance()
        summary = mc.get_histogram_summary("celery_task_duration_seconds")
        assert summary["count"] == 1
        assert summary["sum"] >= 0  # monotonic delta cannot be negative


class TestFailureMetrics:
    """F-22: task_failure increments a dedicated failure counter."""

    def test_failure_signal_increments_failure_counter(self) -> None:
        from intellisource.scheduler.signals import (
            _on_task_failure,
            _on_task_prerun,
        )

        task = _make_task()
        _on_task_prerun(sender=task, task_id="t-3")
        _on_task_failure(sender=task, task_id="t-3")

        mc = MetricsCollector.get_instance()
        assert mc.get_counter_value("celery_task_failures_total") == 1.0

    def test_total_counter_isolated_from_failure_counter(self) -> None:
        """A failure alone (no postrun) must not bump celery_tasks_total."""
        from intellisource.scheduler.signals import _on_task_failure

        task = _make_task()
        _on_task_failure(sender=task, task_id="t-4")

        mc = MetricsCollector.get_instance()
        assert mc.get_counter_value("celery_task_failures_total") == 1.0
        assert mc.get_counter_value("celery_tasks_total") == 0.0
