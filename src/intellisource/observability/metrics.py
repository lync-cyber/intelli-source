"""Metrics collection with counter, gauge, and histogram support.

Provides a singleton MetricsCollector for registering and recording
custom application metrics.
"""

from __future__ import annotations

import threading
from typing import Any


class MetricsCollector:
    """Singleton metrics collector supporting counter, gauge, and histogram metrics."""

    _instance: MetricsCollector | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> MetricsCollector:
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking to avoid race conditions
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._counters: dict[str, float] = {}
                    instance._counter_descriptions: dict[str, str] = {}
                    instance._gauges: dict[str, float] = {}
                    instance._gauge_descriptions: dict[str, str] = {}
                    instance._histograms: dict[str, list[float]] = {}
                    instance._histogram_descriptions: dict[str, str] = {}
                    cls._instance = instance
        return cls._instance

    @classmethod
    def get_instance(cls) -> MetricsCollector:
        """Return the singleton instance."""
        return cls()

    def register_counter(self, name: str, description: str = "") -> None:
        """Register a counter metric."""
        self._counters[name] = 0
        self._counter_descriptions[name] = description

    def increment_counter(self, name: str, amount: float = 1) -> None:
        """Increment a registered counter."""
        if name not in self._counters:
            raise KeyError(f"Counter '{name}' is not registered")
        self._counters[name] += amount

    def get_counter_value(self, name: str) -> float:
        """Get the current value of a counter."""
        if name not in self._counters:
            raise KeyError(f"Counter '{name}' is not registered")
        return self._counters[name]

    def register_gauge(self, name: str, description: str = "") -> None:
        """Register a gauge metric."""
        self._gauges[name] = 0
        self._gauge_descriptions[name] = description

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to a specific value."""
        if name not in self._gauges:
            raise KeyError(f"Gauge '{name}' is not registered")
        self._gauges[name] = value

    def get_gauge_value(self, name: str) -> float:
        """Get the current value of a gauge."""
        if name not in self._gauges:
            raise KeyError(f"Gauge '{name}' is not registered")
        return self._gauges[name]

    def register_histogram(self, name: str, description: str = "") -> None:
        """Register a histogram metric."""
        self._histograms[name] = []
        self._histogram_descriptions[name] = description

    def observe_histogram(self, name: str, value: float) -> None:
        """Record a value in a histogram."""
        if name not in self._histograms:
            raise KeyError(f"Histogram '{name}' is not registered")
        self._histograms[name].append(value)

    def get_histogram_summary(self, name: str) -> dict[str, Any]:
        """Get summary statistics for a histogram."""
        if name not in self._histograms:
            raise KeyError(f"Histogram '{name}' is not registered")
        values = self._histograms[name]
        return {
            "count": len(values),
            "sum": sum(values),
        }
