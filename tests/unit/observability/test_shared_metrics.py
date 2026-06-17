"""Tests for the cross-process Redis-backed metric store (worker exposure).

The worker runs as a prefork pool (multiple child processes), each with its own
``MetricsCollector`` singleton that is never served over HTTP. ``RedisMetricStore``
gives every process a shared sink so the API ``/api/v1/metrics`` endpoint can
surface worker-recorded families (``celery_tasks_total`` etc.) via Redis.
"""

from __future__ import annotations

from typing import Any


class _FakeRedis:
    """Minimal in-memory stand-in for the sync ``redis.Redis`` hash API."""

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


class _BrokenRedis:
    """Every operation raises — exercises graceful degradation."""

    def hset(self, *_args: Any, **_kwargs: Any) -> int:
        raise ConnectionError("redis down")

    def hincrbyfloat(self, *_args: Any, **_kwargs: Any) -> str:
        raise ConnectionError("redis down")

    def hgetall(self, *_args: Any, **_kwargs: Any) -> dict[str, str]:
        raise ConnectionError("redis down")


class TestRedisMetricStoreRoundTrip:
    """register / increment / set / read_all behave like a metric store."""

    def test_increment_counter_round_trips_unlabeled(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_FakeRedis())
        store.register_counter("celery_tasks_total", "Total Celery tasks executed")
        store.increment_counter("celery_tasks_total")
        store.increment_counter("celery_tasks_total")

        entries = {e["name"]: e for e in store.read_all()}
        assert "celery_tasks_total" in entries
        entry = entries["celery_tasks_total"]
        assert entry["type"] == "counter"
        assert entry["series"][""] == 2.0

    def test_increment_counter_round_trips_labeled(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_FakeRedis())
        store.register_counter("pushes_total", "Push attempts")
        store.increment_counter(
            "pushes_total", labels={"channel": "email", "status": "sent"}
        )

        entry = {e["name"]: e for e in store.read_all()}["pushes_total"]
        assert entry["series"]["channel=email,status=sent"] == 1.0

    def test_set_gauge_round_trips(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_FakeRedis())
        store.register_gauge("llm_circuit_open", "1 when any breaker OPEN")
        store.set_gauge("llm_circuit_open", value=1.0)

        entry = {e["name"]: e for e in store.read_all()}["llm_circuit_open"]
        assert entry["type"] == "gauge"
        assert entry["series"][""] == 1.0

    def test_seed_counter_makes_family_appear_at_zero(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_FakeRedis())
        store.seed_counter("celery_tasks_total", "Total Celery tasks executed")

        entry = {e["name"]: e for e in store.read_all()}["celery_tasks_total"]
        assert entry["series"][""] == 0.0

    def test_seed_does_not_clobber_existing_value(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        client = _FakeRedis()
        store = RedisMetricStore(client)
        store.increment_counter("celery_tasks_total")
        store.seed_counter("celery_tasks_total", "desc")

        entry = {e["name"]: e for e in store.read_all()}["celery_tasks_total"]
        assert entry["series"][""] == 1.0


class TestGracefulDegradation:
    """Redis failures must never raise out of metric writes/reads."""

    def test_writes_swallow_redis_errors(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_BrokenRedis())
        store.register_counter("celery_tasks_total")
        store.increment_counter("celery_tasks_total")
        store.set_gauge("llm_circuit_open", value=1.0)  # must not raise

    def test_read_all_returns_empty_on_redis_error(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(_BrokenRedis())
        assert store.read_all() == []

    def test_none_client_is_noop(self) -> None:
        from intellisource.observability.shared_metrics import RedisMetricStore

        store = RedisMetricStore(None)
        store.register_counter("celery_tasks_total")
        store.increment_counter("celery_tasks_total")
        assert store.read_all() == []


class TestRenderer:
    """render_shared_metrics_text emits Prometheus exposition lines."""

    def test_renders_unlabeled_counter_with_help_and_type(self) -> None:
        from intellisource.observability.shared_metrics import (
            render_shared_metrics_text,
        )

        text = render_shared_metrics_text(
            [
                {
                    "name": "celery_tasks_total",
                    "type": "counter",
                    "description": "Total Celery tasks executed",
                    "series": {"": 3.0},
                }
            ]
        )
        assert "# HELP celery_tasks_total Total Celery tasks executed" in text
        assert "# TYPE celery_tasks_total counter" in text
        assert "celery_tasks_total 3.0" in text

    def test_renders_labeled_series(self) -> None:
        from intellisource.observability.shared_metrics import (
            render_shared_metrics_text,
        )

        text = render_shared_metrics_text(
            [
                {
                    "name": "pushes_total",
                    "type": "counter",
                    "description": "Push attempts",
                    "series": {"channel=email,status=sent": 2.0},
                }
            ]
        )
        assert 'pushes_total{channel="email",status="sent"} 2.0' in text

    def test_empty_entries_render_empty_string(self) -> None:
        from intellisource.observability.shared_metrics import (
            render_shared_metrics_text,
        )

        assert render_shared_metrics_text([]) == ""
