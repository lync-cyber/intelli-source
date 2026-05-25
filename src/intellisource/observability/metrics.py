"""Metrics collection with counter, gauge, and histogram support.

Provides a singleton MetricsCollector for registering and recording
custom application metrics.
"""

from __future__ import annotations

import threading
from typing import Any


def _labels_to_key(labels: dict[str, str]) -> str:
    """Stable sorted string key from a labels dict, e.g. 'component=db'."""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


class MetricsCollector:
    """Singleton metrics collector supporting counter, gauge, and histogram metrics."""

    _instance: MetricsCollector | None = None
    _lock: threading.Lock = threading.Lock()

    _counters: dict[str, float]
    _counter_descriptions: dict[str, str]
    _gauges: dict[str, float]
    _gauge_descriptions: dict[str, str]
    _histograms: dict[str, list[float]]
    _histogram_descriptions: dict[str, str]
    # Labeled gauges: {metric_name: {label_key_str: value}}
    _labeled_gauges: dict[str, dict[str, float]]
    _labeled_gauge_labelnames: dict[str, tuple[str, ...]]
    _labeled_gauge_descriptions: dict[str, str]
    # Labeled counters: {metric_name: {label_key_str: value}}
    _labeled_counters: dict[str, dict[str, float]]
    _labeled_counter_labelnames: dict[str, tuple[str, ...]]
    _labeled_counter_descriptions: dict[str, str]

    def __new__(cls) -> MetricsCollector:
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking to avoid race conditions
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._counters = {}
                    instance._counter_descriptions = {}
                    instance._gauges = {}
                    instance._gauge_descriptions = {}
                    instance._histograms = {}
                    instance._histogram_descriptions = {}
                    instance._labeled_gauges = {}
                    instance._labeled_gauge_labelnames = {}
                    instance._labeled_gauge_descriptions = {}
                    instance._labeled_counters = {}
                    instance._labeled_counter_labelnames = {}
                    instance._labeled_counter_descriptions = {}
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

    def iter_counters(self) -> list[tuple[str, str, float]]:
        """Yield (name, description, value) for every registered counter."""
        return [
            (name, self._counter_descriptions.get(name, name), value)
            for name, value in self._counters.items()
        ]

    def iter_gauges(self) -> list[tuple[str, str, float]]:
        """Yield (name, description, value) for every registered gauge."""
        return [
            (name, self._gauge_descriptions.get(name, name), value)
            for name, value in self._gauges.items()
        ]

    def iter_histograms(self) -> list[tuple[str, str, list[float]]]:
        """Yield (name, description, observations) for every histogram."""
        return [
            (name, self._histogram_descriptions.get(name, name), list(values))
            for name, values in self._histograms.items()
        ]

    def register_labeled_gauge(
        self, name: str, labelnames: list[str], description: str = ""
    ) -> None:
        """Register a gauge metric that supports label dimensions.

        Idempotent when called with the same labelnames; raises ValueError if
        labelnames differ from the existing registration.
        """
        canonical = tuple(sorted(labelnames))
        if name in self._labeled_gauges:
            existing = self._labeled_gauge_labelnames[name]
            if existing != canonical:
                raise ValueError(
                    f"Labeled gauge '{name}' already registered with "
                    f"labelnames {list(existing)}, cannot re-register with {labelnames}"
                )
            return
        self._labeled_gauges[name] = {}
        self._labeled_gauge_labelnames[name] = canonical
        self._labeled_gauge_descriptions[name] = description

    def _check_labeled_gauge_keys(self, name: str, labels: dict[str, str]) -> None:
        expected = self._labeled_gauge_labelnames[name]
        actual = tuple(sorted(labels.keys()))
        if actual != expected:
            raise KeyError(
                f"Labeled gauge '{name}' expects labelnames {list(expected)}, "
                f"got labels with keys {list(actual)}"
            )

    def set_labeled_gauge(
        self, name: str, labels: dict[str, str], value: float
    ) -> None:
        """Set the value for a specific label combination on a labeled gauge."""
        if name not in self._labeled_gauges:
            raise KeyError(f"Labeled gauge '{name}' is not registered")
        self._check_labeled_gauge_keys(name, labels)
        label_key = _labels_to_key(labels)
        self._labeled_gauges[name][label_key] = value

    def get_labeled_gauge_value(self, name: str, labels: dict[str, str]) -> float:
        """Get the value for a specific label combination on a labeled gauge."""
        if name not in self._labeled_gauges:
            raise KeyError(f"Labeled gauge '{name}' is not registered")
        self._check_labeled_gauge_keys(name, labels)
        label_key = _labels_to_key(labels)
        if label_key not in self._labeled_gauges[name]:
            raise KeyError(f"Labeled gauge '{name}' has no entry for labels {labels}")
        return self._labeled_gauges[name][label_key]

    def iter_labeled_gauges(
        self,
    ) -> list[tuple[str, str, dict[str, float]]]:
        """Yield (name, description, {label_key: value}) for every labeled gauge."""
        return [
            (
                name,
                self._labeled_gauge_descriptions.get(name, name),
                dict(series),
            )
            for name, series in self._labeled_gauges.items()
        ]

    def register_labeled_counter(
        self, name: str, labelnames: list[str], description: str = ""
    ) -> None:
        """Register a counter metric that supports label dimensions.

        Idempotent when called with the same labelnames; raises ValueError if
        labelnames differ from the existing registration.
        """
        canonical = tuple(sorted(labelnames))
        if name in self._labeled_counters:
            existing = self._labeled_counter_labelnames[name]
            if existing != canonical:
                raise ValueError(
                    f"Labeled counter '{name}' already registered with "
                    f"labelnames {list(existing)}, cannot re-register with {labelnames}"
                )
            return
        self._labeled_counters[name] = {}
        self._labeled_counter_labelnames[name] = canonical
        self._labeled_counter_descriptions[name] = description

    def _check_labeled_counter_keys(self, name: str, labels: dict[str, str]) -> None:
        expected = self._labeled_counter_labelnames[name]
        actual = tuple(sorted(labels.keys()))
        if actual != expected:
            raise KeyError(
                f"Labeled counter '{name}' expects labelnames {list(expected)}, "
                f"got labels with keys {list(actual)}"
            )

    def increment_labeled_counter(
        self, name: str, labels: dict[str, str], amount: float = 1.0
    ) -> None:
        """Increment a labeled counter by amount for the given label combination."""
        if name not in self._labeled_counters:
            raise KeyError(f"Labeled counter '{name}' is not registered")
        self._check_labeled_counter_keys(name, labels)
        label_key = _labels_to_key(labels)
        self._labeled_counters[name][label_key] = (
            self._labeled_counters[name].get(label_key, 0.0) + amount
        )

    def get_labeled_counter_value(self, name: str, labels: dict[str, str]) -> float:
        """Return the current value for a specific label combination.

        Returns 0.0 if the combination has never been incremented.
        """
        if name not in self._labeled_counters:
            raise KeyError(f"Labeled counter '{name}' is not registered")
        self._check_labeled_counter_keys(name, labels)
        label_key = _labels_to_key(labels)
        return self._labeled_counters[name].get(label_key, 0.0)

    def iter_labeled_counters(self) -> list[tuple[str, dict[str, float]]]:
        """Return [(name, {label_key: value})] for every registered labeled counter."""
        return [(name, dict(series)) for name, series in self._labeled_counters.items()]
