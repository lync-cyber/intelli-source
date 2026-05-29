"""Metrics emission helper for the LLM gateway."""

from __future__ import annotations

from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_METRIC_LLM_CALLS_TOTAL = "llm_calls_total"
_METRIC_LLM_FAILURES_TOTAL = "llm_call_failures_total"
_METRIC_LLM_LATENCY = "llm_call_latency_seconds"
_METRIC_LLM_CACHE_HITS_TOTAL = "llm_cache_hits_total"


def _record_cache_hit(call_type: str) -> None:
    """Increment the cache-hit counter for a given call_type."""
    try:
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        mc.increment_labeled_counter(
            _METRIC_LLM_CACHE_HITS_TOTAL, labels={"call_type": call_type}
        )
    except Exception:  # noqa: BLE001 — metric failures must not break LLM path
        logger.exception("failed to record cache-hit metric")


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
