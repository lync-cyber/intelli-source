"""Tests for LLMGateway.stream_complete() SSE streaming.

Covers:
- AC-T070-2: stream_complete uses litellm.acompletion(stream=True), yields chunks
- AC-T070-3: each yielded event has {"content": "...", "done": False}
- AC-T070-4: final event has {"content": "", "done": True, "metadata": {...}}
- AC-T070-4: metadata contains model/input_tokens/output_tokens/latency_ms
- AC-T070-5: CostTracker.log_call called once after stream ends
- AC-T070-5: no error when CostTracker is None
- system_prompt injected as system message
- litellm exception propagates from stream_complete
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.gateway import LLMGateway

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
    def __init__(self, items: list[Any]) -> None:
        self._it = iter(items)

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _chunk(text: str, usage: Any = None, model: str | None = None) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].delta = MagicMock(content=text)
    m.usage = usage
    m.model = model
    return m


def _usage(prompt: int, completion: int) -> MagicMock:
    u = MagicMock()
    u.prompt_tokens = prompt
    u.completion_tokens = completion
    return u


# ---------------------------------------------------------------------------
# AC-T070-2 / AC-T070-3: basic chunk yield
# ---------------------------------------------------------------------------


class TestStreamCompleteChunks:
    """stream_complete yields content chunks with done=False."""

    @pytest.mark.asyncio
    async def test_yields_content_chunks(self) -> None:
        chunks = [_chunk("Hello"), _chunk(" world")]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="hi"):
                events.append(ev)

        content_events = [e for e in events if not e["done"]]
        assert len(content_events) == 2
        assert content_events[0]["content"] == "Hello"
        assert content_events[1]["content"] == " world"
        assert content_events[0]["done"] is False
        assert content_events[1]["done"] is False

    @pytest.mark.asyncio
    async def test_called_with_stream_true(self) -> None:
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter([])
            async for _ in gw.stream_complete(prompt="test"):
                pass
        assert mock_ac.call_args.kwargs.get("stream") is True or (
            len(mock_ac.call_args.args) == 0
            and mock_ac.call_args.kwargs["stream"] is True
        )

    @pytest.mark.asyncio
    async def test_stream_called_with_stream_kwarg_true(self) -> None:
        gw = LLMGateway()
        captured: dict[str, Any] = {}
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:

            async def capture(**kwargs: Any) -> Any:
                captured.update(kwargs)
                return _AsyncIter([])

            mock_ac.side_effect = capture
            async for _ in gw.stream_complete(prompt="test"):
                pass
        assert captured.get("stream") is True


# ---------------------------------------------------------------------------
# AC-T070-4: final event with done=True and metadata
# ---------------------------------------------------------------------------


class TestStreamCompleteTerminalEvent:
    """Final event has done=True with required metadata fields."""

    @pytest.mark.asyncio
    async def test_final_event_done_true(self) -> None:
        chunks = [_chunk("A"), _chunk("B", usage=_usage(10, 5), model="gpt-4o-mini")]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="q"):
                events.append(ev)

        final = events[-1]
        assert final["done"] is True
        assert final["content"] == ""

    @pytest.mark.asyncio
    async def test_final_metadata_fields(self) -> None:
        chunks = [_chunk("hi", usage=_usage(8, 3), model="gpt-4o-mini")]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="q"):
                events.append(ev)

        meta = events[-1]["metadata"]
        assert "input_tokens" in meta
        assert "output_tokens" in meta
        assert "latency_ms" in meta
        assert "model" in meta
        assert meta["input_tokens"] == 8
        assert meta["output_tokens"] == 3
        assert meta["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_token_fallback_when_no_usage(self) -> None:
        chunks = [_chunk("hello world")]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="test"):
                events.append(ev)

        meta = events[-1]["metadata"]
        assert isinstance(meta["input_tokens"], int)
        assert isinstance(meta["output_tokens"], int)


# ---------------------------------------------------------------------------
# system_prompt injection
# ---------------------------------------------------------------------------


class TestStreamCompleteSystemPrompt:
    """system_prompt is prepended as a system message."""

    @pytest.mark.asyncio
    async def test_system_prompt_in_messages(self) -> None:
        gw = LLMGateway()
        captured: dict[str, Any] = {}

        async def capture(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _AsyncIter([])

        with patch("litellm.acompletion", side_effect=capture):
            async for _ in gw.stream_complete(
                prompt="user msg", system_prompt="Be helpful"
            ):
                pass

        msgs = captured["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "Be helpful"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "user msg"


# ---------------------------------------------------------------------------
# AC-T070-5: CostTracker.log_call called once after stream
# ---------------------------------------------------------------------------


class TestStreamCompleteCostTracking:
    """CostTracker.log_call is called once after stream ends."""

    @pytest.mark.asyncio
    async def test_log_call_invoked_once(self) -> None:
        mock_tracker = MagicMock()
        mock_tracker.log_call = AsyncMock()
        gw = LLMGateway(cost_tracker=mock_tracker)
        chunks = [_chunk("ok", usage=_usage(5, 2), model="gpt-4o-mini")]
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            async for _ in gw.stream_complete(prompt="q"):
                pass

        mock_tracker.log_call.assert_called_once()
        record = mock_tracker.log_call.call_args[0][0]
        assert record.status == "success"
        assert record.call_type == "stream_complete"

    @pytest.mark.asyncio
    async def test_no_error_when_cost_tracker_none(self) -> None:
        gw = LLMGateway(cost_tracker=None)
        chunks = [_chunk("ok")]
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="q"):
                events.append(ev)
        assert events[-1]["done"] is True


# ---------------------------------------------------------------------------
# Exception propagation
# ---------------------------------------------------------------------------


class TestStreamCompleteExceptionPropagation:
    """Exceptions from litellm propagate out of stream_complete."""

    @pytest.mark.asyncio
    async def test_litellm_error_propagates(self) -> None:
        gw = LLMGateway()
        with patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("provider error"),
        ):
            with pytest.raises(RuntimeError, match="provider error"):
                async for _ in gw.stream_complete(prompt="q"):
                    pass


# ---------------------------------------------------------------------------
# B-001.1: stream_complete accepts messages= kwarg
# ---------------------------------------------------------------------------


class TestStreamCompleteWithMessages:
    """B-001.1: stream_complete must accept pre-built messages list."""

    @pytest.mark.asyncio
    async def test_messages_kwarg_forwarded_verbatim(self) -> None:
        """When messages= is supplied, it is forwarded to litellm verbatim."""
        gw = LLMGateway()
        captured: dict[str, Any] = {}
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "tool_call_id": "1", "content": "{}"},
            {"role": "user", "content": "summarize"},
        ]
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:

            async def capture(**kwargs: Any) -> Any:
                captured.update(kwargs)
                return _AsyncIter([])

            mock_ac.side_effect = capture
            async for _ in gw.stream_complete(messages=msgs):
                pass
        assert captured.get("messages") == msgs

    @pytest.mark.asyncio
    async def test_messages_takes_precedence_over_prompt(self) -> None:
        """When both prompt and messages are given, messages wins."""
        gw = LLMGateway()
        captured: dict[str, Any] = {}
        msgs: list[dict[str, Any]] = [{"role": "user", "content": "from messages"}]
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:

            async def capture(**kwargs: Any) -> Any:
                captured.update(kwargs)
                return _AsyncIter([])

            mock_ac.side_effect = capture
            async for _ in gw.stream_complete(prompt="from prompt", messages=msgs):
                pass
        assert captured["messages"] == msgs

    @pytest.mark.asyncio
    async def test_raises_when_neither_prompt_nor_messages(self) -> None:
        """At least one of prompt= / messages= must be supplied."""
        gw = LLMGateway()
        with pytest.raises(ValueError, match="prompt|messages"):
            async for _ in gw.stream_complete():
                pass


# ---------------------------------------------------------------------------
# tools=: accumulate function-call deltas + finish_reason into done metadata
# ---------------------------------------------------------------------------


def _tc_frag(
    index: int,
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> MagicMock:
    frag = MagicMock()
    frag.index = index
    frag.id = call_id
    if name is None and arguments is None:
        frag.function = None
    else:
        frag.function = MagicMock(name=name, arguments=arguments)
        # MagicMock(name=...) sets the mock's repr name, not a .name attr.
        frag.function.name = name
        frag.function.arguments = arguments
    return frag


def _tool_chunk(
    *,
    tool_calls: list[MagicMock] | None = None,
    content: str = "",
    finish_reason: str | None = None,
) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].delta = MagicMock(content=content)
    m.choices[0].delta.tool_calls = tool_calls
    m.choices[0].finish_reason = finish_reason
    m.usage = None
    m.model = None
    return m


_TOOLS_ARG: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "search", "parameters": {}}}
]


class TestStreamCompleteWithTools:
    """tools= accumulates tool_call deltas and surfaces them in done metadata."""

    @pytest.mark.asyncio
    async def test_tool_call_fragments_assembled_by_index(self) -> None:
        chunks = [
            _tool_chunk(
                tool_calls=[
                    _tc_frag(0, call_id="tc-1", name="search", arguments='{"q":')
                ]
            ),
            _tool_chunk(tool_calls=[_tc_frag(0, arguments=' "ai"}')]),
            _tool_chunk(finish_reason="tool_calls"),
        ]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="q", tools=_TOOLS_ARG):
                events.append(ev)

        meta = events[-1]["metadata"]
        assert meta["finish_reason"] == "tool_calls"
        assert meta["tool_calls"] == [
            {
                "id": "tc-1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "ai"}'},
            }
        ]

    @pytest.mark.asyncio
    async def test_tools_forwarded_to_litellm(self) -> None:
        gw = LLMGateway()
        captured: dict[str, Any] = {}
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:

            async def capture(**kwargs: Any) -> Any:
                captured.update(kwargs)
                return _AsyncIter([_tool_chunk(finish_reason="stop")])

            mock_ac.side_effect = capture
            async for _ in gw.stream_complete(prompt="q", tools=_TOOLS_ARG):
                pass
        assert captured.get("tools") == _TOOLS_ARG

    @pytest.mark.asyncio
    async def test_no_tool_calls_gives_none_with_finish_reason(self) -> None:
        chunks = [
            _tool_chunk(content="answer", finish_reason=None),
            _tool_chunk(finish_reason="stop"),
        ]
        gw = LLMGateway()
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_ac:
            mock_ac.return_value = _AsyncIter(chunks)
            events = []
            async for ev in gw.stream_complete(prompt="q", tools=_TOOLS_ARG):
                events.append(ev)

        content_events = [e for e in events if not e["done"]]
        assert content_events[0]["content"] == "answer"
        meta = events[-1]["metadata"]
        assert meta["tool_calls"] is None
        assert meta["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_invalid_tools_rejected(self) -> None:
        gw = LLMGateway()
        with pytest.raises(ValueError):
            async for _ in gw.stream_complete(prompt="q", tools=[{"bad": "shape"}]):
                pass
