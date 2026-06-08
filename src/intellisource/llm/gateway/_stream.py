"""StreamMixin: streaming LLM completion for LLMGateway."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from intellisource.llm.cost_tracker import LLMCallRecord
from intellisource.llm.gateway._metrics import _record_llm_call
from intellisource.llm.gateway._routing import resolve_model
from intellisource.observability.logging import get_logger

if TYPE_CHECKING:
    from intellisource.llm.gateway._proto import _GatewayProto

logger = get_logger(__name__)


class _StreamMixin:
    """Provides stream_complete() for streaming LLM responses."""

    async def stream_complete(
        self: _GatewayProto,
        prompt: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        task_type: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream LLM completion via litellm.acompletion(stream=True).

        Accepts either a single-turn `prompt` (+ optional system_prompt) or a
        pre-built `messages` list (multi-turn / tool history). One of the two
        must be supplied.

        When `tools` is supplied the function-calling deltas are accumulated by
        index across chunks and the final event's metadata carries the assembled
        ``tool_calls`` list plus ``finish_reason``, so a streaming agent loop can
        decide whether the turn ended in tool calls or a final answer.

        Yields dicts of shape:
        - {"content": "...", "done": False} per chunk
        - {"content": "", "done": True, "metadata": {...}} final
        """
        if messages is None and prompt is None:
            raise ValueError("stream_complete requires either prompt= or messages=")
        if tools is not None:
            self._validate_tools(tools)

        resolved_model = resolve_model(
            self._routing_config, model, task_type, fallback_default=True
        )

        call_kwargs = self._prepare_litellm_kwargs(
            resolved_model=resolved_model,
            prompt=prompt,
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            task_type=task_type,
            stream=True,
            response_format=None,
        )
        if tools is not None:
            call_kwargs["tools"] = tools
        call_messages = call_kwargs["messages"]

        start_time = time.monotonic()
        accumulated_content = ""
        input_tokens = 0
        output_tokens = 0
        final_model = resolved_model
        tool_call_parts: dict[int, dict[str, str]] = {}
        finish_reason = ""

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
                if tools is not None:
                    _accumulate_tool_call_deltas(chunk, tool_call_parts)
                    fr = _chunk_finish_reason(chunk)
                    if fr:
                        finish_reason = fr
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
        if tools is not None:
            assembled = [
                {
                    "id": part["id"],
                    "type": "function",
                    "function": {
                        "name": part["name"],
                        "arguments": part["arguments"],
                    },
                }
                for _, part in sorted(tool_call_parts.items())
                if part["name"]
            ]
            metadata["tool_calls"] = assembled or None
            metadata["finish_reason"] = finish_reason

        if self._cost_tracker is not None or self._session_factory is not None:
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
            await self._emit_call_log(record)

        yield {"content": "", "done": True, "metadata": metadata}


def _chunk_finish_reason(chunk: Any) -> str:
    """Read ``choices[0].finish_reason`` from a stream chunk, or '' if absent."""
    try:
        return str(chunk.choices[0].finish_reason or "")
    except (AttributeError, IndexError, TypeError):
        return ""


def _accumulate_tool_call_deltas(chunk: Any, parts: dict[int, dict[str, str]]) -> None:
    """Merge a chunk's ``delta.tool_calls`` fragments into ``parts`` by index.

    litellm streams each tool call as index-keyed fragments: the first carries
    ``id`` / ``function.name``, later ones append ``function.arguments`` string
    pieces. Fragments may arrive out of order or with missing fields, so every
    field is merged defensively.
    """
    try:
        deltas = chunk.choices[0].delta.tool_calls
    except (AttributeError, IndexError):
        return
    if not deltas:
        return
    for frag in deltas:
        index = getattr(frag, "index", 0)
        if not isinstance(index, int):
            index = 0
        slot = parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
        frag_id = getattr(frag, "id", None)
        if frag_id:
            slot["id"] = str(frag_id)
        fn = getattr(frag, "function", None)
        if fn is not None:
            name = getattr(fn, "name", None)
            if name:
                slot["name"] = str(name)
            args = getattr(fn, "arguments", None)
            if args:
                slot["arguments"] += str(args)
