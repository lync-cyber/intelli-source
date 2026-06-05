"""CompleteMixin: single-turn text completion for LLMGateway."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._extra_body import (
    build_extra_body,
    extract_reasoning_content,
)
from intellisource.llm.gateway._metrics import _record_llm_call
from intellisource.llm.gateway._types import LLMResult
from intellisource.llm.prompt_builder import PromptBuilder

if TYPE_CHECKING:
    from intellisource.llm.gateway._proto import _GatewayProto


class _CompleteMixin:
    """Provides complete() and the private _call_with_retry() helper."""

    async def complete(
        self: _GatewayProto,
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
                self._warn(
                    "No model config for task_type '%s', using default_model",
                    task_type,
                )
                resolved_model = self._routing_config["default_model"]["model"]

        if resolved_model is None:
            resolved_model = "gpt-4o-mini"

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
            self._warn(
                "Prompt tokens (%d) exceed limit (%d) for model '%s', truncating",
                estimated,
                effective_limit,
                resolved_model,
            )
            prompt = PromptBuilder.truncate_content(
                prompt, effective_limit, resolved_model
            )

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

        task_cfg_for_extra = (
            self._routing_config.get("models", {}).get(task_type)
            if task_type is not None
            else None
        )
        extra_body = build_extra_body(resolved_model, task_cfg_for_extra, profile)
        if extra_body is not None:
            call_kwargs["extra_body"] = extra_body

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
        reasoning_content = extract_reasoning_content(response.choices[0].message)
        metadata: dict[str, Any] = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "latency_ms": elapsed_ms,
            "model": response.model,
            "reasoning_content": reasoning_content,
        }

        result = LLMResult(content=content, metadata=metadata)

        if self._cache is not None and cache_key_parts is not None:
            await self._cache.set(
                content_fingerprint=cache_key_parts["content_fingerprint"],
                call_type=cache_key_parts["call_type"],
                prompt_version=cache_key_parts["prompt_version"],
                result=result,
            )

        if self._cost_tracker is not None or self._session_factory is not None:
            response_model = str(response.model)
            record = LLMCallRecord(
                model=response_model,
                provider=(
                    response_model.split("/")[0] if "/" in response_model else "unknown"
                ),
                call_type="complete",
                input_tokens=int(response.usage.prompt_tokens),
                output_tokens=int(response.usage.completion_tokens),
                latency_ms=int(elapsed_ms),
                input_length=len(prompt),
                output_length=len(content),
                status="success",
            )
            await self._emit_call_log(record)

        return result

    async def _call_with_retry(
        self: _GatewayProto,
        call_kwargs: dict[str, Any],
        prompt: str,
        task_type: str | None = None,
    ) -> Any:
        """Invoke litellm.acompletion with exponential backoff retry.

        Delegates to _unified_call_with_retry; caller handles fallback.
        """
        model = str(call_kwargs.get("model", "unknown"))

        async def _call_fn() -> Any:
            return await self._acompletion(**call_kwargs)

        return await self._unified_call_with_retry(
            _call_fn,
            model=model,
            call_type=task_type or "unknown",
            enable_circuit_breaker=True,
            task_type=task_type,
        )
