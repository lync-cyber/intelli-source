"""Retry, circuit-breaker, fallback, and logging mixin for LLMGateway."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
)

from intellisource.core.errors import ErrorCategory
from intellisource.llm.circuit_breaker import CircuitOpenError
from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._routing import _classify_error
from intellisource.llm.gateway._types import LLMResult

if TYPE_CHECKING:
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker
    from intellisource.llm.fallback import FallbackManager

logger = logging.getLogger(__name__)


class _RetryMixin:
    """Provides unified retry / circuit-breaker / fallback / logging helpers."""

    # These attributes are set in LLMGateway.__init__
    _retry_wait: Any
    _cost_tracker: CostTracker | None
    _fallback_manager: FallbackManager | None
    circuit_breaker: CircuitBreaker | None
    _session_factory: Any  # Callable returning async ctx mgr → AsyncSession

    async def _emit_call_log(self, record: LLMCallRecord) -> None:
        """Persist an LLMCallRecord through whichever logging path is wired.

        Explicit ``cost_tracker`` wins (legacy unit-test path with a mocked
        session). Otherwise a session is opened per call via
        ``session_factory`` and a fresh ``CostTracker`` writes through it.
        Both arms swallow exceptions so logging never breaks the LLM call
        path.
        """
        if self._cost_tracker is not None:
            try:
                await self._cost_tracker.log_call(record)
            except Exception as exc:
                logger.warning(
                    "Failed to log %s call via cost_tracker: %s",
                    record.call_type,
                    exc,
                )
            return
        if self._session_factory is not None:
            from intellisource.llm.cost_tracker import CostTracker as _CostTracker

            try:
                async with self._session_factory() as session:
                    await _CostTracker(session).log_call(record)
            except Exception as exc:
                logger.warning(
                    "Failed to log %s call via session_factory: %s",
                    record.call_type,
                    exc,
                )

    async def _unified_call_with_retry(
        self,
        call_fn: Callable[[], Awaitable[Any]],
        *,
        model: str,
        call_type: str,
        enable_circuit_breaker: bool = True,
        task_type: str | None = None,
    ) -> Any:
        """Unified retry + circuit breaker + fallback for all LLM call paths.

        Does not perform prompt construction or response parsing.

        Args:
            call_fn: Async callable with no arguments that invokes the provider.
            model: Resolved model identifier for logging.
            call_type: "complete" / "chat" / "stream" for log records.
            enable_circuit_breaker: Whether to check/record circuit breaker state.
            task_type: Task type for fallback routing and retry logging.
        """
        if enable_circuit_breaker and self.circuit_breaker is not None:
            allowed = await self.circuit_breaker.allow_request()
            if not allowed:
                await self._log_failure(
                    model=model,
                    call_type=call_type,
                    status="circuit_open",
                    error_message="circuit breaker OPEN — request rejected",
                )
                raise CircuitOpenError()

        _response: Any = None
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=self._retry_wait,
                retry=retry_if_exception(
                    lambda e: _classify_error(e) is ErrorCategory.RECOVERABLE_TRANSIENT
                ),
                reraise=True,
            ):
                with attempt:
                    attempt_num = attempt.retry_state.attempt_number
                    if attempt_num > 1:
                        await self._log_retry(
                            model=model,
                            retry_attempt=attempt_num - 1,
                            call_type=call_type,
                        )
                    try:
                        _response = await call_fn()
                    except Exception:
                        if enable_circuit_breaker and self.circuit_breaker is not None:
                            await self.circuit_breaker.record_failure()
                        raise
        except Exception as exc:
            # Retries exhausted (or non-retryable error) — persist a terminal
            # audit row before re-raising so failures are not invisible in
            # llm_call_logs. "Timeout"-named providers map to status='timeout',
            # everything else to 'error'.
            status = "timeout" if "Timeout" in type(exc).__name__ else "error"
            await self._log_failure(
                model=model,
                call_type=call_type,
                status=status,
                error_message=str(exc) or type(exc).__name__,
            )
            raise

        if enable_circuit_breaker and self.circuit_breaker is not None:
            await self.circuit_breaker.record_success()
        return _response

    async def _log_failure(
        self,
        *,
        model: str,
        call_type: str,
        status: str,
        error_message: str,
    ) -> None:
        """Persist a terminal-failure LLMCallRecord (no tokens consumed)."""
        record = LLMCallRecord(
            model=model,
            provider=model.split("/")[0] if "/" in model else "unknown",
            call_type=call_type,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            input_length=0,
            output_length=0,
            status=status,
            error_message=error_message,
        )
        await self._emit_call_log(record)

    async def _try_fallback(
        self,
        exc: BaseException,
        task_type: str | None,
        prompt: str,
    ) -> Any:
        """Attempt fallback execution; re-raise original exc when not possible.

        Behavior contract:
        - fallback_manager is None → re-raise original exc
        - task_type not registered (KeyError from execute_fallback) → re-raise
          original exc
        - fallback function itself raises → that exception propagates (the original
          transient exc is intentionally lost; the more recent fallback failure is
          more diagnostic for operators).
        """
        if self._fallback_manager is not None and task_type is not None:
            try:
                return await self._fallback_manager.execute_fallback(
                    task_type=task_type,
                    input_data=prompt,
                )
            except KeyError:
                raise exc
        raise exc

    async def _log_retry(self, model: str, retry_attempt: int, call_type: str) -> None:
        """Write a retry record to LLMCallLog when cost_tracker is available."""
        if self._cost_tracker is None:
            logger.warning(
                "LLM call retry attempt %d for model '%s'", retry_attempt, model
            )
            return
        record = LLMCallRecord(
            model=model,
            provider=model.split("/")[0] if "/" in model else "unknown",
            call_type=call_type,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            input_length=0,
            output_length=0,
            status="retry",
            retry_attempt=retry_attempt,
        )
        try:
            await self._cost_tracker.log_call(record)
        except Exception as log_exc:
            logger.warning("Failed to log retry to LLMCallLog: %s", log_exc)

    async def _log_cache_hit(
        self,
        cached: LLMResult,
        call_type: str,
        input_text: str,
    ) -> None:
        """Persist a cache-hit event to LLMCallLog (AC-T052-4).

        Records status='cached' with input_tokens=0 to indicate no tokens
        were consumed by the LLM provider on this request. Skipped silently
        when no cost_tracker is configured or when persistence fails, so
        cache lookups never block the request path.
        """
        if self._cost_tracker is None:
            return
        model_name = str(cached.metadata.get("model", "unknown"))
        output_tokens = int(cached.metadata.get("output_tokens", 0))
        record = LLMCallRecord(
            model=model_name,
            provider=model_name.split("/")[0] if "/" in model_name else "unknown",
            call_type=call_type,
            input_tokens=0,
            output_tokens=output_tokens,
            latency_ms=0,
            input_length=len(input_text),
            output_length=len(cached.content),
            status="cached",
        )
        try:
            await self._cost_tracker.log_call(record)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to log cache-hit to LLMCallLog: %s", exc)
