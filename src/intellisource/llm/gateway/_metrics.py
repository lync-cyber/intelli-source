"""Metrics emission helper for the LLM gateway."""

from __future__ import annotations

from typing import Any

from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_METRIC_LLM_CALLS_TOTAL = "llm_calls_total"
_METRIC_LLM_FAILURES_TOTAL = "llm_call_failures_total"
_METRIC_LLM_LATENCY = "llm_call_latency_seconds"
_METRIC_LLM_CACHE_HITS_TOTAL = "llm_cache_hits_total"
_METRIC_LLM_PROMPT_CACHE_TOKENS = "llm_prompt_cache_hit_tokens_total"


def _extract_cached_tokens(usage: Any) -> int:
    """Provider prompt-cache hit tokens from a response usage object.

    litellm normalises automatic provider caching (DeepSeek context cache,
    OpenAI cached prefix) into ``usage.prompt_tokens_details.cached_tokens``;
    an absent or malformed shape yields 0 so the call path never breaks on it.
    """
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None and isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
    if details is None:
        return 0
    cached = getattr(details, "cached_tokens", None)
    if cached is None and isinstance(details, dict):
        cached = details.get("cached_tokens")
    try:
        return int(cached) if cached is not None else 0
    except (TypeError, ValueError):
        return 0


def _record_prompt_cache_hit(model: str, cached_tokens: int) -> None:
    """Add provider prompt-cache hit tokens to the per-model counter."""
    if cached_tokens <= 0:
        return
    try:
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        mc.increment_labeled_counter(
            _METRIC_LLM_PROMPT_CACHE_TOKENS,
            labels={"model": model},
            amount=cached_tokens,
        )
    except Exception:  # noqa: BLE001 — metric failures must not break LLM path
        logger.exception("failed to record prompt-cache metric")


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
