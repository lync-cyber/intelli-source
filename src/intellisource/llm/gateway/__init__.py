"""LLM unified gateway with schema enforcement.

Provides LLMGateway for calling LLMs via litellm, SchemaEnforcer for
validating outputs against JSON Schema, and SchemaValidationError.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import litellm
from tenacity import wait_exponential

from intellisource.llm.circuit_breaker import CircuitOpenError as CircuitOpenError
from intellisource.llm.gateway._chat import _ChatMixin
from intellisource.llm.gateway._complete import _CompleteMixin
from intellisource.llm.gateway._metrics import _record_llm_call as _record_llm_call
from intellisource.llm.gateway._queue import _QueueMixin
from intellisource.llm.gateway._retry import _RetryMixin
from intellisource.llm.gateway._routing import _classify_error, _load_routing_config
from intellisource.llm.gateway._stream import _StreamMixin
from intellisource.llm.gateway._types import (
    LLMOutputError,
    LLMResult,
    SchemaEnforcer,
    SchemaValidationError,
)
from intellisource.llm.model_config import ModelRoutingConfig
from intellisource.llm.priority_queue import PriorityQueue

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker
    from intellisource.llm.fallback import FallbackManager

logger = logging.getLogger(__name__)


class LLMGateway(_RetryMixin, _CompleteMixin, _ChatMixin, _StreamMixin, _QueueMixin):
    """Unified LLM calling interface built on litellm."""

    _CONTEXT_WINDOWS: dict[str, int] = {
        "gpt-4o-mini": 128000,
        "gpt-4o": 128000,
        "claude-3-haiku-20240307": 200000,
        "claude-sonnet-4-20250514": 200000,
    }
    _DEFAULT_CONTEXT_WINDOW = 128000

    _INTERACTIVE_TASK_TYPES: frozenset[str] = frozenset(
        ["search", "chat", "interactive", "query"]
    )

    def __init__(
        self,
        cache: LLMCache | None = None,
        cost_tracker: CostTracker | None = None,
        fallback_manager: FallbackManager | None = None,
        _retry_wait: Any = None,
        circuit_breaker: CircuitBreaker | None = None,
        priority_queue: PriorityQueue | None = None,
    ) -> None:
        self._default_temperature: float = 0.7
        self._default_max_tokens: int = 4096
        self._routing_config: dict[str, Any] = _load_routing_config()
        self._model_routing = ModelRoutingConfig(self._routing_config)
        self._cache: LLMCache | None = cache
        self._cost_tracker: CostTracker | None = cost_tracker
        self._fallback_manager: FallbackManager | None = fallback_manager
        self._retry_wait: Any = (
            _retry_wait
            if _retry_wait is not None
            else wait_exponential(multiplier=1, min=1, max=30)
        )
        self.circuit_breaker: CircuitBreaker | None = circuit_breaker
        self._priority_queue: PriorityQueue | None = priority_queue
        self._register_metrics()

    def _register_metrics(self) -> None:
        try:
            from intellisource.observability.metrics import MetricsCollector

            mc = MetricsCollector.get_instance()
            mc.register_labeled_counter(
                "llm_calls_total",
                labelnames=["model"],
                description="Total LLM calls executed by model",
            )
            mc.register_labeled_counter(
                "llm_call_failures_total",
                labelnames=["model"],
                description="Total LLM calls that failed by model",
            )
        except Exception:  # noqa: BLE001 — metric failures must not break LLM path
            logger.exception("failed to register LLM gateway metrics")

    @staticmethod
    async def _acompletion(**kwargs: Any) -> Any:
        """Thin wrapper around litellm.acompletion for testability."""
        return await litellm.acompletion(**kwargs)

    def _warn(self, msg: str, *args: Any) -> None:
        """Log a warning via the gateway module logger (patchable in tests)."""
        logger.warning(msg, *args)

    def estimate_tokens(self, text: str, model: str) -> int:
        """Estimate token count for text.

        Prefers litellm.token_counter; falls back to len(text)//4 heuristic.

        Args:
            text: Input text to count tokens for.
            model: Model identifier for tokenizer selection.

        Returns:
            Estimated token count.
        """
        try:
            count = litellm.token_counter(model=model, text=text)
            if isinstance(count, int):
                return count
            return len(text) // 4
        except Exception:
            return len(text) // 4


__all__ = [
    "CircuitOpenError",
    "LLMGateway",
    "LLMOutputError",
    "LLMResult",
    "SchemaEnforcer",
    "SchemaValidationError",
    "_classify_error",
    "_load_routing_config",
    "_record_llm_call",
]
