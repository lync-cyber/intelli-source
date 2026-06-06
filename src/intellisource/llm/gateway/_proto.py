"""Structural view of ``LLMGateway`` as seen by its mixins.

The gateway is assembled from several mixins (``_CompleteMixin``, ``_ChatMixin``,
``_StreamMixin``, ``_EmbedMixin``, ``_RetryMixin``) that call
across one another and read shared state set in ``LLMGateway.__init__``. Each
mixin alone is not a complete gateway, so its methods annotate ``self`` with this
Protocol instead of ``Any`` — that restores ``mypy --strict`` coverage of the
shared attributes and cross-mixin calls (model routing, cache, cost tracking,
circuit breaker, fallback) without forcing a single monolithic class.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker, LLMCallRecord
    from intellisource.llm.fallback import FallbackManager
    from intellisource.llm.gateway._types import LLMResult
    from intellisource.llm.model_config import ModelRoutingConfig


class _GatewayProto(Protocol):
    """Shared attributes + cross-mixin methods visible to every gateway mixin."""

    # --- state set in LLMGateway.__init__ ---
    _default_temperature: float
    _default_max_tokens: int
    _routing_config: dict[str, Any]
    _model_routing: ModelRoutingConfig
    _cache: LLMCache | None
    _cost_tracker: CostTracker | None
    _fallback_manager: FallbackManager | None
    _retry_wait: Any
    circuit_breaker: CircuitBreaker | None
    _session_factory: Callable[[], Any] | None

    # --- class-level constants on LLMGateway ---
    _CONTEXT_WINDOWS: dict[str, int]
    _DEFAULT_CONTEXT_WINDOW: int

    # --- provider call wrappers (staticmethods on LLMGateway; declared as
    #     read-only Protocol methods so a staticmethod satisfies them) ---
    async def _acompletion(self, **kwargs: Any) -> Any: ...

    async def _aembedding(self, **kwargs: Any) -> Any: ...

    # --- cross-mixin methods ---
    def _warn(self, msg: str, *args: Any) -> None: ...

    def estimate_tokens(self, text: str, model: str) -> int: ...

    def _validate_tools(self, tools: Any) -> None: ...

    async def _emit_call_log(self, record: LLMCallRecord) -> None: ...

    async def _log_cache_hit(
        self, cached: LLMResult, call_type: str, input_text: str
    ) -> None: ...

    async def _try_fallback(
        self, exc: BaseException, task_type: str | None, prompt: str
    ) -> Any: ...

    async def _unified_call_with_retry(
        self,
        call_fn: Callable[[], Awaitable[Any]],
        *,
        model: str,
        call_type: str,
        enable_circuit_breaker: bool = ...,
        task_type: str | None = ...,
    ) -> Any: ...

    async def _call_with_retry(
        self,
        call_kwargs: dict[str, Any],
        prompt: str,
        task_type: str | None = ...,
    ) -> Any: ...
