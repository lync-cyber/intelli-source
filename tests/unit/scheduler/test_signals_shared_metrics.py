"""B-014: Celery signal handlers mirror celery_* counters into the shared store.

Worker processes record ``celery_tasks_total`` / ``celery_task_failures_total``
into the cross-process Redis store so the API ``/api/v1/metrics`` endpoint can
surface them (the worker's own per-process collector is never served over HTTP).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> Any:
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: Any = None,
        mapping: dict[str, Any] | None = None,
    ) -> int:
        h = self.store.setdefault(name, {})
        if mapping:
            for k, v in mapping.items():
                h[k] = str(v)
        if key is not None:
            h[key] = str(value)
        return 1

    def hincrbyfloat(self, name: str, key: str, amount: float) -> str:
        h = self.store.setdefault(name, {})
        cur = float(h.get(key, "0")) + float(amount)
        h[key] = str(cur)
        return h[key]

    def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.store.get(name, {}))


def _make_task(headers: dict[str, Any] | None = None) -> SimpleNamespace:
    request = SimpleNamespace(headers=dict(headers or {}))
    return SimpleNamespace(request=request)


def _patch_shared_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point signals + the shared-store accessor at a fake-redis-backed store."""
    from intellisource.observability import shared_metrics

    store = shared_metrics.RedisMetricStore(_FakeRedis())
    monkeypatch.setattr(shared_metrics, "get_shared_metric_store", lambda: store)
    # signals imports the symbol; patch its binding too if already imported.
    import intellisource.scheduler.signals as signals_mod

    monkeypatch.setattr(
        signals_mod, "get_shared_metric_store", lambda: store, raising=False
    )
    return store


def _series_value(store: Any, name: str, label_key: str = "") -> float:
    entry = {e["name"]: e for e in store.read_all()}.get(name)
    assert entry is not None, f"{name} not present in shared store"
    return entry["series"].get(label_key, 0.0)


class TestSignalsWriteSharedStore:
    """postrun / failure handlers replicate counters into the shared store."""

    def test_postrun_increments_shared_celery_tasks_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _patch_shared_store(monkeypatch)
        from intellisource.scheduler.signals import _on_task_postrun, _on_task_prerun

        task = _make_task()
        _on_task_prerun(sender=task, task_id="t-1")
        _on_task_postrun(sender=task, task_id="t-1", state="SUCCESS")

        assert _series_value(store, "celery_tasks_total") == 1.0

    def test_failure_increments_shared_failure_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _patch_shared_store(monkeypatch)
        from intellisource.scheduler.signals import _on_task_failure

        task = _make_task()
        _on_task_failure(sender=task, task_id="t-2")

        assert _series_value(store, "celery_task_failures_total") == 1.0

    def test_shared_write_failure_does_not_break_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken shared store must never raise out of a signal handler."""
        from intellisource.observability import shared_metrics

        broken = shared_metrics.RedisMetricStore(None)  # no-op client

        def _boom() -> Any:
            raise RuntimeError("store init failed")

        import intellisource.scheduler.signals as signals_mod

        # Even if the accessor itself raises, the local-collector path still works.
        monkeypatch.setattr(
            signals_mod, "get_shared_metric_store", _boom, raising=False
        )
        del broken

        task = _make_task()
        signals_mod._on_task_prerun(sender=task, task_id="t-3")
        signals_mod._on_task_postrun(sender=task, task_id="t-3", state="SUCCESS")

        # Local collector still recorded the task despite the shared-store failure.
        assert (
            MetricsCollector.get_instance().get_counter_value("celery_tasks_total")
            == 1.0
        )
