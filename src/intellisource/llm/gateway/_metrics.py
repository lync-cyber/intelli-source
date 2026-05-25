"""Metrics emission helper for the LLM gateway."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_METRIC_LLM_CALLS_TOTAL = "llm_calls_total"
_METRIC_LLM_FAILURES_TOTAL = "llm_call_failures_total"
_METRIC_LLM_LATENCY = "llm_call_latency_seconds"


def _record_llm_call(
    *, latency_seconds: float, success: bool, model: str = "unknown"
) -> None:
    """Emit per-call metrics on the singleton MetricsCollector."""
    try:
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        if _METRIC_LLM_LATENCY not in mc._histograms:
            mc.register_histogram(
                _METRIC_LLM_LATENCY,
                "Wall-clock latency (seconds) of LLM provider calls",
            )
        mc.increment_labeled_counter(_METRIC_LLM_CALLS_TOTAL, labels={"model": model})
        if not success:
            mc.increment_labeled_counter(
                _METRIC_LLM_FAILURES_TOTAL, labels={"model": model}
            )
        mc.observe_histogram(_METRIC_LLM_LATENCY, latency_seconds)
    except Exception:  # noqa: BLE001 — metric failures must not break LLM path
        logger.exception("failed to record LLM call metrics")
