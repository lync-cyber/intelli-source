"""llm_circuit_open registers at CircuitBreaker construction (not lazily).

The gauge must exist (at 0) from the moment a breaker is built — so that a
quiet API process still exposes ``llm_circuit_open`` on /api/v1/metrics —
which the API does at startup via ``build_llm_gateway``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def reset_metrics_singleton() -> Any:
    MetricsCollector._instance = None
    yield
    MetricsCollector._instance = None


def test_circuit_breaker_init_registers_llm_circuit_open_gauge() -> None:
    from intellisource.llm.circuit_breaker import CircuitBreaker

    mc = MetricsCollector.get_instance()
    assert "llm_circuit_open" not in mc._gauges

    CircuitBreaker(redis=MagicMock())

    assert "llm_circuit_open" in mc._gauges
    assert mc.get_gauge_value("llm_circuit_open") == 0.0


def test_circuit_breaker_init_metric_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken collector must not prevent breaker construction."""
    from intellisource.llm.circuit_breaker import CircuitBreaker

    def _broken_get_instance(cls: type) -> Any:
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr(
        "intellisource.observability.metrics.MetricsCollector.get_instance",
        classmethod(_broken_get_instance),
    )
    # Must not raise.
    CircuitBreaker(redis=MagicMock())
