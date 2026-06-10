"""CompleteMixin: single-turn text completion for LLMGateway."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._extra_body import extract_reasoning_content
from intellisource.llm.gateway._metrics import _record_llm_call
from intellisource.llm.gateway._routing import resolve_model, run_with_model_failover
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

        resolved_model = resolve_model(
            self._routing_config, model, task_type, warn=self._warn
        )

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

        def _complete_kwargs(model_id: str) -> dict[str, Any]:
            return self._prepare_litellm_kwargs(
                resolved_model=model_id,
                prompt=prompt,
                messages=None,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                task_type=task_type,
                stream=False,
                response_format=response_format,
            )

        async def _complete_with_model(model_id: str) -> Any:
            return await self._call_with_retry(
                call_kwargs=_complete_kwargs(model_id),
                prompt=prompt,
                task_type=task_type,
            )

        # Primary model then each configured fallback (task-keyed); a task_type
        # with no fallbacks, or none at all, stays single-model.
        models_to_try = [resolved_model]
        if task_type is not None:
            models_to_try.extend(self._model_routing.get_fallback_models(task_type))

        start_time = time.monotonic()

        def _on_model_failure(model_id: str, _exc: BaseException) -> None:
            _record_llm_call(
                latency_seconds=time.monotonic() - start_time,
                success=False,
                model=model_id,
            )

        try:
            response, successful_model = await run_with_model_failover(
                models_to_try, _complete_with_model, on_failure=_on_model_failure
            )
        except BaseException as exc:
            return cast(LLMResult, await self._try_fallback(exc, task_type, prompt))
        elapsed_seconds = time.monotonic() - start_time
        elapsed_ms = elapsed_seconds * 1000
        _record_llm_call(
            latency_seconds=elapsed_seconds, success=True, model=successful_model
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
