"""StreamMixin: streaming LLM completion for LLMGateway."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._metrics import _record_llm_call

logger = logging.getLogger(__name__)


class _StreamMixin:
    """Provides stream_complete() for streaming LLM responses."""

    async def stream_complete(
        self: Any,
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
                lambda: self._acompletion(**call_kwargs),
                model=resolved_model,
                call_type="stream",
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
