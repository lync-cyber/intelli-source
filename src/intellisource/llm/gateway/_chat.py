"""ChatMixin: messages-style LLM calls with tool support for LLMGateway."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._extra_body import (
    build_extra_body,
    extract_reasoning_content,
)
from intellisource.llm.gateway._metrics import _record_llm_call
from intellisource.llm.gateway._types import (
    LLMOutputError,
    LLMResult,
    SchemaEnforcer,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)


class _ChatMixin:
    """Provides chat() and the _validate_tools() helper."""

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
        self: Any,
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

        task_cfg_for_extra = self._routing_config.get("models", {}).get("chat")
        profile_for_extra = self._model_routing.get_profile(resolved_model)
        extra_body = build_extra_body(
            resolved_model, task_cfg_for_extra, profile_for_extra
        )
        if extra_body is not None:
            call_kwargs["extra_body"] = extra_body

        async def _chat_call_fn() -> Any:
            try:
                return await self._acompletion(**call_kwargs)
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
                    return await self._acompletion(**degraded_kwargs)
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
                enable_circuit_breaker=True,
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
        reasoning_content = extract_reasoning_content(response.choices[0].message)
        metadata: dict[str, Any] = {
            "tool_calls": response.choices[0].message.tool_calls,
            "finish_reason": response.choices[0].finish_reason,
            "usage": dict(response.usage) if response.usage else {},
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "latency_ms": elapsed_ms,
            "model": response.model,
            "reasoning_content": reasoning_content,
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

        if self._cost_tracker is not None or self._session_factory is not None:
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
            await self._emit_call_log(record)

        return result
