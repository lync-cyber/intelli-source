"""LLM unified gateway with schema enforcement.

Provides LLMGateway for calling LLMs via litellm, SchemaEnforcer for
validating outputs against JSON Schema, and SchemaValidationError.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, cast

import litellm
from tenacity import wait_exponential

from intellisource.llm.circuit_breaker import CircuitOpenError as CircuitOpenError
from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._retry import _RetryMixin
from intellisource.llm.gateway._routing import _classify_error, _load_routing_config
from intellisource.llm.gateway._types import (
    LLMOutputError,
    LLMResult,
    SchemaEnforcer,
    SchemaValidationError,
)
from intellisource.llm.model_config import ModelRoutingConfig
from intellisource.llm.priority_queue import PriorityLevel, PriorityQueue, QueuedRequest
from intellisource.llm.prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from intellisource.llm.cache import LLMCache
    from intellisource.llm.circuit_breaker import CircuitBreaker
    from intellisource.llm.cost_tracker import CostTracker
    from intellisource.llm.fallback import FallbackManager

logger = logging.getLogger(__name__)

# B-005: LLM gateway labeled counter names.
_METRIC_LLM_CALLS_TOTAL = "llm_calls_total"
_METRIC_LLM_FAILURES_TOTAL = "llm_call_failures_total"
_METRIC_LLM_LATENCY = "llm_call_latency_seconds"


def _record_llm_call(
    *, latency_seconds: float, success: bool, model: str = "unknown"
) -> None:
    """Emit per-call metrics on the singleton MetricsCollector.

    llm_calls_total and llm_call_failures_total are labeled by model so
    per-model call and failure rates are available in Prometheus queries.
    llm_call_latency_seconds remains an unlabeled histogram for p99 alerting.
    """
    try:
        from intellisource.observability.metrics import MetricsCollector

        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter(
            _METRIC_LLM_CALLS_TOTAL,
            labelnames=["model"],
            description="Total LLM calls executed by model",
        )
        mc.register_labeled_counter(
            _METRIC_LLM_FAILURES_TOTAL,
            labelnames=["model"],
            description="Total LLM calls that failed by model",
        )
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


class LLMGateway(_RetryMixin):
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
        prompt_builder: PromptBuilder | None = None,
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
            prompt_builder: Optional PromptBuilder. When provided and
                cache_key_parts is given, missing ``call_type`` and
                ``prompt_version`` keys are auto-filled from the builder so
                callers do not have to compute the template hash themselves.

        Returns:
            LLMResult with content and metadata.
        """
        if prompt_builder is not None and cache_key_parts is not None:
            cache_key_parts.setdefault("call_type", prompt_builder.call_type)
            cache_key_parts.setdefault("prompt_version", prompt_builder.prompt_version)

        # Check cache before calling LLM
        if self._cache is not None and cache_key_parts is not None:
            cached = await self._cache.get(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
            )
            if cached is not None:
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
            _record_llm_call(
                latency_seconds=time.monotonic() - start_time,
                success=False,
                model=resolved_model,
            )
            return cast(LLMResult, await self._try_fallback(exc, task_type, prompt))
        elapsed_seconds = time.monotonic() - start_time
        elapsed_ms = elapsed_seconds * 1000
        _record_llm_call(
            latency_seconds=elapsed_seconds, success=True, model=resolved_model
        )

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

        resolved_model = model
        if resolved_model is None:
            models = self._routing_config.get("models", {})
            if "chat" in models:
                resolved_model = models["chat"]["model"]
            else:
                from intellisource.core.errors import ErrorCategory, LLMError

                default_cfg = self._routing_config.get("default_model")
                if default_cfg is None:
                    raise LLMError(
                        "No model configured for 'chat' task and no default_model "
                        "found in routing config.",
                        category=ErrorCategory.UNRECOVERABLE,
                    )
                resolved_model = default_cfg["model"]

        call_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
        }
        if tools is not None:
            call_kwargs["tools"] = tools
        if response_format is not None:
            call_kwargs["response_format"] = response_format

        async def _chat_call_fn() -> Any:
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

        fallback_text = " ".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "user"
        )
        start_time = time.monotonic()
        try:
            response = await self._unified_call_with_retry(
                _chat_call_fn,
                model=resolved_model,
                call_type="chat",
                operation_id="chat",
                enable_fallback=False,
                enable_circuit_breaker=True,
                fallback_input=fallback_text,
                task_type="chat",
            )
        except BaseException as exc:
            _record_llm_call(
                latency_seconds=time.monotonic() - start_time,
                success=False,
                model=resolved_model,
            )
            if self._fallback_manager is not None:
                return cast(
                    LLMResult,
                    await self._try_fallback(exc, "chat", fallback_text),
                )
            raise
        elapsed_seconds = time.monotonic() - start_time
        elapsed_ms = elapsed_seconds * 1000
        _record_llm_call(
            latency_seconds=elapsed_seconds, success=True, model=resolved_model
        )

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
            enforcer = SchemaEnforcer(schema)
            try:
                enforcer.validate(content)
            except SchemaValidationError as exc:
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

        Delegates to _unified_call_with_retry; caller handles fallback.
        """
        model = str(call_kwargs.get("model", "unknown"))

        async def _call_fn() -> Any:
            return await litellm.acompletion(**call_kwargs)

        return await self._unified_call_with_retry(
            _call_fn,
            model=model,
            call_type=task_type or "unknown",
            operation_id=task_type or "unknown",
            enable_fallback=False,
            enable_circuit_breaker=True,
            task_type=task_type,
        )

    async def enqueue_request(
        self,
        prompt: str,
        model: str,
        task_type: str | None = None,
    ) -> None:
        """Enqueue an LLM request into the priority queue.

        Interactive task types (search, chat, interactive, query) use
        PriorityLevel.HIGH; all other task types — including task_type=None —
        use PriorityLevel.NORMAL.
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

    async def stream_complete(
        self,
        prompt: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task_type: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream LLM completion via litellm.acompletion(stream=True).

        Accepts either a single-turn `prompt` (+ optional system_prompt) or a
        pre-built `messages` list (multi-turn / tool history). One of the two
        must be supplied.

        Yields dicts of shape:
        - {"content": "...", "done": False} per chunk
        - {"content": "", "done": True, "metadata": {...}} final
        """
        if messages is None and prompt is None:
            raise ValueError("stream_complete requires either prompt= or messages=")

        resolved_model = model
        if resolved_model is None and task_type is not None:
            models = self._routing_config.get("models", {})
            if task_type in models:
                resolved_model = models[task_type]["model"]
            else:
                resolved_model = self._routing_config["default_model"]["model"]
        if resolved_model is None:
            resolved_model = "gpt-4o-mini"

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

        call_messages: list[dict[str, Any]]
        if messages is not None:
            call_messages = list(messages)
        else:
            call_messages = []
            if system_prompt is not None:
                call_messages.append({"role": "system", "content": system_prompt})
            call_messages.append({"role": "user", "content": prompt})

        call_kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": call_messages,
            "temperature": resolved_temperature,
            "max_tokens": resolved_max_tokens,
            "stream": True,
        }
        if profile is not None:
            call_kwargs["timeout"] = profile.timeout_seconds

        start_time = time.monotonic()
        accumulated_content = ""
        input_tokens = 0
        output_tokens = 0
        final_model = resolved_model

        try:
            response = await self._unified_call_with_retry(
                lambda: litellm.acompletion(**call_kwargs),
                model=resolved_model,
                call_type="stream",
                operation_id=task_type or "stream",
                enable_fallback=False,
                enable_circuit_breaker=True,
                task_type=task_type,
            )
            async for chunk in response:
                delta_content = ""
                try:
                    delta_content = chunk.choices[0].delta.content or ""
                except (AttributeError, IndexError):
                    pass
                if delta_content:
                    accumulated_content += delta_content
                    yield {"content": delta_content, "done": False}
                # Capture usage from last chunk if available
                try:
                    usage = chunk.usage
                    if usage is not None:
                        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                except AttributeError:
                    pass
                try:
                    chunk_model = chunk.model
                    if chunk_model:
                        final_model = str(chunk_model)
                except AttributeError:
                    pass
        except asyncio.CancelledError:
            _record_llm_call(
                latency_seconds=time.monotonic() - start_time,
                success=False,
                model=resolved_model,
            )
            return
        except BaseException:
            _record_llm_call(
                latency_seconds=time.monotonic() - start_time,
                success=False,
                model=resolved_model,
            )
            raise

        # Fallback token estimates when streaming response omits usage
        if input_tokens == 0:
            input_tokens = (
                sum(len(str(m.get("content", ""))) for m in call_messages) // 4
            )
        if output_tokens == 0:
            output_tokens = len(accumulated_content) // 4

        elapsed_seconds = time.monotonic() - start_time
        elapsed_ms = elapsed_seconds * 1000
        _record_llm_call(
            latency_seconds=elapsed_seconds, success=True, model=final_model
        )
        metadata: dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": elapsed_ms,
            "model": final_model,
        }

        if self._cost_tracker is not None:
            input_length = (
                len(prompt)
                if prompt is not None
                else sum(len(str(m.get("content", ""))) for m in call_messages)
            )
            record = LLMCallRecord(
                model=final_model,
                provider=(
                    final_model.split("/")[0] if "/" in final_model else "unknown"
                ),
                call_type="stream_complete",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int(elapsed_ms),
                input_length=input_length,
                output_length=len(accumulated_content),
                status="success",
            )
            try:
                await self._cost_tracker.log_call(record)
            except Exception as log_exc:
                logger.warning(
                    "Failed to log stream_complete call to CostTracker: %s", log_exc
                )

        yield {"content": "", "done": True, "metadata": metadata}

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
]
