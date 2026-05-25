"""Protocol type for mixin self-type contract.

Mixins reference attributes and methods that are defined on LLMGateway
and _RetryMixin. This Protocol declares them so mypy --strict does not
report attribute access errors on untyped self in mixin methods.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from intellisource.llm.model_config import ModelRoutingConfig

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker
    from intellisource.llm.fallback import FallbackManager
    from intellisource.llm.gateway._types import LLMResult
    from intellisource.llm.priority_queue import PriorityQueue


class _GatewayProtocol(Protocol):
    """Self-type contract shared by all LLMGateway mixins."""

    _default_temperature: float
    _default_max_tokens: int
    _routing_config: dict[str, Any]
    _model_routing: ModelRoutingConfig
    _cache: LLMCache | None
    _cost_tracker: CostTracker | None
    _fallback_manager: FallbackManager | None
    _retry_wait: Any
    circuit_breaker: CircuitBreaker | None
    _priority_queue: PriorityQueue | None
    _CONTEXT_WINDOWS: dict[str, int]
    _DEFAULT_CONTEXT_WINDOW: int
    _INTERACTIVE_TASK_TYPES: frozenset[str]

    async def _unified_call_with_retry(
        self,
        call_fn: Callable[[], Awaitable[Any]],
        *,
        model: str,
        call_type: str,
        enable_circuit_breaker: bool = ...,
        task_type: str | None = ...,
    ) -> Any: ...

    async def _try_fallback(
        self,
        exc: BaseException,
        task_type: str | None,
        prompt: str,
    ) -> Any: ...

    async def _log_cache_hit(
        self,
        cached: LLMResult,
        call_type: str,
        input_text: str,
    ) -> None: ...

    def estimate_tokens(self, text: str, model: str) -> int: ...

    def stream_complete(
        self,
        prompt: str | None,
        model: str | None,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        task_type: str | None,
        *,
        messages: list[dict[str, Any]] | None,
    ) -> AsyncGenerator[dict[str, Any], None]: ...
