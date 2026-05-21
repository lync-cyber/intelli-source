"""LLM unified gateway with schema enforcement.

Provides LLMGateway for calling LLMs via litellm, SchemaEnforcer for
validating outputs against JSON Schema, and SchemaValidationError.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker
    from intellisource.llm.fallback import FallbackManager
    from intellisource.llm.priority_queue import PriorityQueue

import jsonschema
import litellm
from pydantic import ValidationError as PydanticValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from intellisource.core.errors import ErrorCategory, IntelliSourceError, LLMError
from intellisource.llm.priority_queue import PriorityLevel, PriorityQueue, QueuedRequest
from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.model_config import ModelRoutingConfig, load_model_config
from intellisource.llm.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = str(
    Path(__file__).resolve().parents[3] / "config" / "llm_models.yaml"
)

_TRANSIENT_EXCEPTION_NAMES = frozenset(
    [
        "Timeout",
        "APIConnectionError",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
    ]
)

_UNRECOVERABLE_EXCEPTION_NAMES = frozenset(
    [
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "UnsupportedParamsError",
        "ContextWindowExceededError",
        "ContentPolicyViolationError",
    ]
)


def _classify_error(exc: BaseException) -> ErrorCategory:
    """Map an exception to an ErrorCategory for retry decisions.

    IntelliSourceError subclasses are classified by their own .category.
    litellm exceptions are classified by class name. Unknown exceptions
    default to RECOVERABLE_DEGRADED.
    """
    if isinstance(exc, IntelliSourceError):
        return exc.category

    exc_type_name = type(exc).__name__
    if exc_type_name in _TRANSIENT_EXCEPTION_NAMES:
        return ErrorCategory.RECOVERABLE_TRANSIENT
    if exc_type_name in _UNRECOVERABLE_EXCEPTION_NAMES:
        return ErrorCategory.UNRECOVERABLE
    return ErrorCategory.RECOVERABLE_DEGRADED


def _load_routing_config() -> dict[str, Any]:
    """Load model routing config from env var or default path.

    Falls back to an empty config if the file does not exist.
    """
    config_path = os.environ.get("IS_LLM_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
    path = Path(config_path)
    if not path.exists():
        logger.warning(
            "LLM routing config not found at '%s', using empty config",
            config_path,
        )
        return {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {},
            "profiles": {},
        }
    try:
        return load_model_config(config_path)
    except PydanticValidationError as exc:
        raise LLMError(
            f"LLM config validation failed: {exc}",
            category=ErrorCategory.UNRECOVERABLE,
        ) from exc
    except ValueError as exc:
        raise LLMError(
            f"LLM config file error: {exc}",
            category=ErrorCategory.UNRECOVERABLE,
        ) from exc


class SchemaValidationError(LLMError):
    """Raised when LLM output fails JSON Schema validation."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_DEGRADED,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class LLMOutputError(LLMError):
    """Raised when LLM output cannot be parsed or validated after enforcement."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.RECOVERABLE_DEGRADED,
        recovery_hint: str = "",
    ) -> None:
        super().__init__(message, category=category, recovery_hint=recovery_hint)


class CircuitOpenError(LLMError):
    """Raised when a request is blocked because the circuit breaker is OPEN."""

    def __init__(self, message: str = "Circuit breaker is OPEN") -> None:
        super().__init__(message, category=ErrorCategory.RECOVERABLE_DEGRADED)


@dataclass
class LLMResult:
    """Result from an LLM completion call."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SchemaEnforcer:
    """Validates LLM output against a JSON Schema."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    def validate(self, raw_output: str) -> dict[str, Any]:
        """Parse and validate raw LLM output against the schema.

        Args:
            raw_output: Raw JSON string from LLM.

        Returns:
            Parsed and validated dictionary.

        Raises:
            SchemaValidationError: If parsing or validation fails.
        """
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"Invalid JSON: {exc}") from exc

        try:
            jsonschema.validate(instance=data, schema=self._schema)
        except jsonschema.ValidationError as exc:
            raise SchemaValidationError(
                f"Schema validation failed: {exc.message}"
            ) from exc

        return dict(data)


class LLMGateway:
    """Unified LLM calling interface built on litellm."""

    _CONTEXT_WINDOWS: dict[str, int] = {
        "gpt-4o-mini": 128000,
        "gpt-4o": 128000,
        "claude-3-haiku-20240307": 200000,
        "claude-sonnet-4-20250514": 200000,
    }
    _DEFAULT_CONTEXT_WINDOW = 128000

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

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task_type: str | None = None,
        cache_key_parts: dict[str, str] | None = None,
        max_input_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Call an LLM with standardized parameters.

        Args:
            prompt: The user prompt.
            model: Model identifier (overrides task_type routing).
            system_prompt: Optional system message.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            task_type: Task type for automatic model routing.
            cache_key_parts: Optional dict with keys content_fingerprint,
                call_type, prompt_version for cache lookup/storage.
            max_input_tokens: Optional max input token limit. If set or if
                estimated tokens exceed 80% of model context window, the
                user prompt is truncated.

        Returns:
            LLMResult with content and metadata.
        """
        # Check cache before calling LLM
        if self._cache is not None and cache_key_parts is not None:
            cached = await self._cache.get(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
            )
            if cached is not None:
                # AC-T052-4: record cache hit to LLMCallLog with
                # status=cached, input_tokens=0
                await self._log_cache_hit(
                    cached=cached,
                    call_type=cache_key_parts["call_type"],
                    input_text=prompt,
                )
                return cached

        resolved_model = model

        if resolved_model is None and task_type is not None:
            models = self._routing_config.get("models", {})
            if task_type in models:
                resolved_model = models[task_type]["model"]
            else:
                logger.warning(
                    "No model config for task_type '%s', using default_model",
                    task_type,
                )
                resolved_model = self._routing_config["default_model"]["model"]

        if resolved_model is None:
            resolved_model = "gpt-4o-mini"

        # Token truncation: apply if max_input_tokens is set or if
        # estimated tokens exceed 80% of the model context window.
        estimated = self.estimate_tokens(prompt, resolved_model)
        context_window = self._CONTEXT_WINDOWS.get(
            resolved_model, self._DEFAULT_CONTEXT_WINDOW
        )
        threshold = int(context_window * 0.8)
        effective_limit: int | None = None

        if max_input_tokens is not None and estimated > max_input_tokens:
            effective_limit = max_input_tokens
        elif estimated > threshold:
            effective_limit = threshold

        if effective_limit is not None:
            logger.warning(
                "Prompt tokens (%d) exceed limit (%d) for model '%s', truncating",
                estimated,
                effective_limit,
                resolved_model,
            )
            prompt = PromptBuilder.truncate_content(
                prompt, effective_limit, resolved_model
            )

        # Resolve temperature/max_tokens from profile or gateway defaults
        profile = self._model_routing.get_profile(resolved_model)
        resolved_temperature = temperature
        if resolved_temperature is None:
            resolved_temperature = (
                profile.temperature
                if profile is not None
                else self._default_temperature
            )
        resolved_max_tokens = max_tokens
        if resolved_max_tokens is None:
            resolved_max_tokens = (
                profile.max_tokens if profile is not None else self._default_max_tokens
            )

        messages: list[dict[str, str]] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        call_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "temperature": resolved_temperature,
            "max_tokens": resolved_max_tokens,
        }
        if profile is not None:
            call_kwargs["timeout"] = profile.timeout_seconds
        if response_format is not None:
            call_kwargs["response_format"] = response_format

        start_time = time.monotonic()
        try:
            response = await self._call_with_retry(
                call_kwargs=call_kwargs,
                prompt=prompt,
                task_type=task_type,
            )
        except BaseException as exc:
            return cast(LLMResult, await self._try_fallback(exc, task_type, prompt))
        elapsed_ms = (time.monotonic() - start_time) * 1000

        content: str = response.choices[0].message.content
        metadata: dict[str, Any] = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "latency_ms": elapsed_ms,
            "model": response.model,
        }

        result = LLMResult(content=content, metadata=metadata)

        # Cache the result after successful LLM call
        if self._cache is not None and cache_key_parts is not None:
            await self._cache.set(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
                result=result,
            )

        return result

    def _validate_tools(self, tools: Any) -> None:
        """Validate tools list structure before sending to litellm.

        Args:
            tools: The tools argument to validate.

        Raises:
            ValueError: If tools is not a list[dict] or any dict lacks
                required 'type' and 'function' keys.
        """
        if not isinstance(tools, list):
            raise ValueError(
                f"tools must be a list of dicts, got: {type(tools).__name__}"
            )
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                raise ValueError(
                    f"tools[{i}] must be a dict, got: {type(tool).__name__}"
                )
            if "type" not in tool:
                raise ValueError(f"tools[{i}] missing required key 'type'")
            if "function" not in tool:
                raise ValueError(f"tools[{i}] missing required key 'function'")

    async def _chat_call_with_retry(
        self,
        call_kwargs: dict[str, Any],
    ) -> Any:
        """Invoke litellm.acompletion for chat() with retry.

        Retries RECOVERABLE_TRANSIENT errors up to 3 times (4 total calls).
        On UnsupportedParamsError, retries once without tools/response_format.
        """
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(4),
            wait=self._retry_wait,
            retry=retry_if_exception(
                lambda e: _classify_error(e) is ErrorCategory.RECOVERABLE_TRANSIENT
            ),
            reraise=True,
        ):
            with attempt:
                try:
                    return await litellm.acompletion(**call_kwargs)
                except Exception as exc:
                    if type(exc).__name__ == "UnsupportedParamsError":
                        logger.warning(
                            "Provider does not support tools/response_format; "
                            "retrying without them: %s",
                            exc,
                        )
                        degraded_kwargs = {
                            k: v
                            for k, v in call_kwargs.items()
                            if k not in ("tools", "response_format")
                        }
                        return await litellm.acompletion(**degraded_kwargs)
                    raise
        return None  # unreachable; satisfies mypy

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        schema: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResult:
        """Call an LLM with a messages-style API (function calling / JSON mode).

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                Passed to litellm without modification (SS-2).
            tools: Optional list of tool/function dicts. Each must contain
                'type' and 'function' keys (SS-1 validation).
            response_format: Optional response format dict, e.g.
                {"type": "json_object"}.
            schema: Optional JSON Schema dict. When provided and the LLM returns
                invalid JSON, SchemaEnforcer.validate() is called exactly once
                (AC-4 / SS-3). Raises LLMOutputError if enforcement also fails.
            model: Model identifier override.

        Returns:
            LLMResult with content and metadata (tool_calls, finish_reason, usage).

        Raises:
            ValueError: If tools fails structural validation (SS-1).
            LLMOutputError: If JSON output is invalid and SchemaEnforcer fails.
        """
        if tools is not None:
            self._validate_tools(tools)

        resolved_model = model or "gpt-4o-mini"

        call_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
        }
        if tools is not None:
            call_kwargs["tools"] = tools
        if response_format is not None:
            call_kwargs["response_format"] = response_format

        start_time = time.monotonic()
        response = await self._chat_call_with_retry(call_kwargs)
        elapsed_ms = (time.monotonic() - start_time) * 1000

        content: str = response.choices[0].message.content or ""
        metadata: dict[str, Any] = {
            "tool_calls": response.choices[0].message.tool_calls,
            "finish_reason": response.choices[0].finish_reason,
            "usage": dict(response.usage) if response.usage else {},
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "latency_ms": elapsed_ms,
            "model": response.model,
        }

        if schema is not None:
            try:
                json.loads(content)
            except json.JSONDecodeError:
                enforcer = SchemaEnforcer(schema)
                try:
                    enforcer.validate(content)
                except Exception as exc:
                    raise LLMOutputError(
                        f"LLM output failed JSON validation: {exc}"
                    ) from exc

        result = LLMResult(content=content, metadata=metadata)

        if self._cost_tracker is not None:
            record = LLMCallRecord(
                model=str(response.model),
                provider=(
                    str(response.model).split("/")[0]
                    if "/" in str(response.model)
                    else "unknown"
                ),
                call_type="chat",
                input_tokens=int(response.usage.prompt_tokens),
                output_tokens=int(response.usage.completion_tokens),
                latency_ms=int(elapsed_ms),
                input_length=sum(len(str(m.get("content", ""))) for m in messages),
                output_length=len(content),
                status="success",
            )
            try:
                await self._cost_tracker.log_call(record)
            except Exception as log_exc:
                logger.warning("Failed to log chat call to CostTracker: %s", log_exc)

        return result

    async def _call_with_retry(
        self,
        call_kwargs: dict[str, Any],
        prompt: str,
        task_type: str | None = None,
    ) -> Any:
        """Invoke litellm.acompletion with exponential backoff retry.

        Retries only RECOVERABLE_TRANSIENT errors, up to 3 times (4 total calls).
        Logs each retry attempt via cost_tracker when available.
        Raises on exhaustion; caller handles fallback.
        """
        if self.circuit_breaker is not None:
            allowed = await self.circuit_breaker.allow_request()
            if not allowed:
                raise CircuitOpenError()

        _last_exc: BaseException | None = None
        _response: Any = None
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
                        model=str(call_kwargs.get("model", "unknown")),
                        retry_attempt=attempt_num - 1,
                        call_type=task_type or "unknown",
                    )
                try:
                    _response = await litellm.acompletion(**call_kwargs)
                except Exception as exc:
                    _last_exc = exc
                    if self.circuit_breaker is not None:
                        await self.circuit_breaker.record_failure()
                    raise
        if self.circuit_breaker is not None:
            await self.circuit_breaker.record_success()
        return _response

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

    _INTERACTIVE_TASK_TYPES: frozenset[str] = frozenset(
        ["search", "chat", "interactive", "query"]
    )

    async def enqueue_request(
        self,
        prompt: str,
        model: str,
        task_type: str | None = None,
    ) -> None:
        """Enqueue an LLM request into the priority queue.

        Interactive task types (search, chat, interactive, query) use
        PriorityLevel.HIGH; all other task types use PriorityLevel.NORMAL.
        """
        if self._priority_queue is None:
            raise RuntimeError("No priority_queue configured on LLMGateway")
        priority = (
            PriorityLevel.HIGH
            if task_type in self._INTERACTIVE_TASK_TYPES
            else PriorityLevel.NORMAL
        )
        req = QueuedRequest(prompt=prompt, model=model, priority=priority)
        await self._priority_queue.enqueue(req)

    async def process_queue_item(self) -> Any:
        """Dequeue one request from the priority queue and execute it via litellm.

        Returns the LLM response or None if no queue is configured.
        """
        if self._priority_queue is None:
            return None
        req = await self._priority_queue.dequeue()
        call_kwargs: dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        return await self._call_with_retry(
            call_kwargs=call_kwargs,
            prompt=req.prompt,
            task_type=None,
        )

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
