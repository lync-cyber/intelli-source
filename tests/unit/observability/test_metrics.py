"""Tests for T-006: Observability module -- metrics collection.

Covers:
  AC-058: MetricsCollector can register and record custom metrics
          (counter, gauge, histogram)
"""

from __future__ import annotations

import pytest

# ===========================================================================
# AC-058: MetricsCollector -- registration and recording
# ===========================================================================


class TestMetricsCollectorImport:
    """MetricsCollector must be importable from observability.metrics."""

    def test_import_metrics_collector(self) -> None:
        """MetricsCollector class must be importable."""
        from intellisource.observability.metrics import MetricsCollector

        assert MetricsCollector is not None

    def test_metrics_collector_is_instantiable(self) -> None:
        """MetricsCollector must be instantiable (or obtainable via factory/singleton)."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        assert collector is not None


class TestMetricsCollectorCounter:
    """AC-058: MetricsCollector supports counter metrics (monotonically increasing)."""

    def test_register_counter(self) -> None:
        """A counter metric can be registered by name."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_counter("requests_total", description="Total requests")
        # Registration should not raise

    def test_increment_counter(self) -> None:
        """A registered counter can be incremented and its value retrieved."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_counter("requests_total", description="Total requests")
        collector.increment_counter("requests_total")
        collector.increment_counter("requests_total")

        value = collector.get_counter_value("requests_total")
        assert value == 2, f"Expected counter=2, got {value}"

    def test_increment_counter_with_amount(self) -> None:
        """A counter can be incremented by a specified amount."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_counter("bytes_sent", description="Bytes sent")
        collector.increment_counter("bytes_sent", amount=100)
        collector.increment_counter("bytes_sent", amount=50)

        value = collector.get_counter_value("bytes_sent")
        assert value == 150, f"Expected counter=150, got {value}"

    def test_increment_unregistered_counter_raises(self) -> None:
        """Incrementing a counter that was not registered must raise an error."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        with pytest.raises((KeyError, ValueError)):
            collector.increment_counter("nonexistent")


class TestMetricsCollectorGauge:
    """AC-058: MetricsCollector supports gauge metrics (can go up and down)."""

    def test_register_gauge(self) -> None:
        """A gauge metric can be registered by name."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_gauge("queue_length", description="Queue length")

    def test_set_gauge_value(self) -> None:
        """A gauge value can be set directly."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_gauge("queue_length", description="Queue length")
        collector.set_gauge("queue_length", 42)

        value = collector.get_gauge_value("queue_length")
        assert value == 42, f"Expected gauge=42, got {value}"

    def test_gauge_can_decrease(self) -> None:
        """A gauge value can decrease (unlike a counter)."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_gauge("active_tasks", description="Active tasks")
        collector.set_gauge("active_tasks", 10)
        collector.set_gauge("active_tasks", 5)

        value = collector.get_gauge_value("active_tasks")
        assert value == 5, f"Expected gauge=5, got {value}"

    def test_set_unregistered_gauge_raises(self) -> None:
        """Setting a gauge that was not registered must raise an error."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        with pytest.raises((KeyError, ValueError)):
            collector.set_gauge("nonexistent", 10)


class TestMetricsCollectorHistogram:
    """AC-058: MetricsCollector supports histogram metrics (value distributions)."""

    def test_register_histogram(self) -> None:
        """A histogram metric can be registered by name."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_histogram(
            "request_latency_ms", description="Request latency"
        )

    def test_observe_histogram(self) -> None:
        """Values can be recorded (observed) in a histogram."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        collector.register_histogram(
            "request_latency_ms", description="Request latency"
        )
        collector.observe_histogram("request_latency_ms", 120.5)
        collector.observe_histogram("request_latency_ms", 85.3)
        collector.observe_histogram("request_latency_ms", 200.0)

        summary = collector.get_histogram_summary("request_latency_ms")
        assert summary["count"] == 3, f"Expected count=3, got {summary['count']}"
        # Sum should be close to 120.5 + 85.3 + 200.0 = 405.8
        assert abs(summary["sum"] - 405.8) < 0.01, (
            f"Expected sum~405.8, got {summary['sum']}"
        )

    def test_observe_unregistered_histogram_raises(self) -> None:
        """Observing a histogram that was not registered must raise an error."""
        from intellisource.observability.metrics import MetricsCollector

        collector = MetricsCollector()
        with pytest.raises((KeyError, ValueError)):
            collector.observe_histogram("nonexistent", 1.0)


class TestMetricsCollectorSingleton:
    """AC-058: MetricsCollector uses singleton pattern for global sharing."""

    def test_singleton_returns_same_instance(self) -> None:
        """MetricsCollector.get_instance() or equivalent must return the same object."""
        from intellisource.observability.metrics import MetricsCollector

        # The singleton may be exposed via get_instance(), instance(), or __new__
        if hasattr(MetricsCollector, "get_instance"):
            a = MetricsCollector.get_instance()
            b = MetricsCollector.get_instance()
        else:
            a = MetricsCollector()
            b = MetricsCollector()
        assert a is b, "MetricsCollector singleton should return the same instance"


class TestMetricsCollectorModuleExports:
    """Observability __init__.py must export key components."""

    def test_metrics_collector_exported_from_init(self) -> None:
        """MetricsCollector must be importable from observability package."""
        from intellisource.observability import MetricsCollector

        assert MetricsCollector is not None
