"""chat() path integrates LLMCache.

Only complete() had a cache path; chat() (used by /search/chat via the flexible
agent loop) never consulted the cache, so identical chat requests always hit the
LLM API. These tests pin the chat() caching contract:

- An identical second chat() call is served from cache (no second LLM call).
- Tool-loop intermediate steps (finish_reason != 'stop' or tool_calls present)
  are NOT cached — only a final 'stop' answer with no tool_calls.
- cache_key_parts=None opts out entirely (current behavior preserved).
- The cache key varies with the messages, so different histories miss.
- A cache hit logs status='cached' and increments llm_cache_hits_total.
"""

from __future__ import annotations

import fnmatch
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.cache import LLMCache
from intellisource.llm.gateway import LLMGateway


class _FakeRedis:
    """Minimal in-memory async Redis stand-in for cache round-trip tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def scan_iter(self, match: str, count: int = 100) -> Any:  # noqa: ARG002
        for key in list(self._store):
            if fnmatch.fnmatch(key, match):
                yield key

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                removed += 1
        return removed


_MESSAGES = [{"role": "user", "content": "what is rag?"}]
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "search the corpus",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _make_response(
    content: str = "answer",
    finish_reason: str = "stop",
    tool_calls: list[Any] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = tool_calls
    resp.choices[0].finish_reason = finish_reason
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.model = "gpt-4o-mini"
    return resp


@pytest.mark.asyncio
async def test_identical_chat_second_call_served_from_cache() -> None:
    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    resp = _make_response(content="cached-me", finish_reason="stop", tool_calls=None)
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache)
        r1 = await gw.chat(
            messages=_MESSAGES,
            tools=_TOOLS,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        r2 = await gw.chat(
            messages=_MESSAGES,
            tools=_TOOLS,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        assert mock_litellm.acompletion.await_count == 1
    assert r1.content == "cached-me"
    assert r2.content == "cached-me"


@pytest.mark.asyncio
async def test_chat_not_cached_when_tool_calls_present() -> None:
    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    resp = _make_response(
        content="", finish_reason="tool_calls", tool_calls=[MagicMock()]
    )
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache)
        await gw.chat(
            messages=_MESSAGES,
            tools=_TOOLS,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        await gw.chat(
            messages=_MESSAGES,
            tools=_TOOLS,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        assert mock_litellm.acompletion.await_count == 2


@pytest.mark.asyncio
async def test_chat_not_cached_when_finish_reason_not_stop() -> None:
    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    resp = _make_response(content="partial", finish_reason="length", tool_calls=None)
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache)
        await gw.chat(
            messages=_MESSAGES,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        await gw.chat(
            messages=_MESSAGES,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        assert mock_litellm.acompletion.await_count == 2


@pytest.mark.asyncio
async def test_chat_no_caching_when_key_parts_none() -> None:
    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    resp = _make_response(content="x", finish_reason="stop", tool_calls=None)
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache)
        await gw.chat(messages=_MESSAGES, model="gpt-4o-mini")
        await gw.chat(messages=_MESSAGES, model="gpt-4o-mini")
        assert mock_litellm.acompletion.await_count == 2


@pytest.mark.asyncio
async def test_chat_different_messages_miss() -> None:
    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    resp = _make_response(content="x", finish_reason="stop", tool_calls=None)
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache)
        await gw.chat(
            messages=[{"role": "user", "content": "A"}],
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        await gw.chat(
            messages=[{"role": "user", "content": "B"}],
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        assert mock_litellm.acompletion.await_count == 2


@pytest.mark.asyncio
async def test_chat_cache_hit_logs_cached_and_increments_metric() -> None:
    from intellisource.observability.metrics import MetricsCollector  # noqa: PLC0415

    cache = LLMCache(redis=_FakeRedis(), ttl=3600)
    tracker = AsyncMock()
    tracker.log_call = AsyncMock()
    resp = _make_response(content="hit", finish_reason="stop", tool_calls=None)
    mc = MetricsCollector.get_instance()
    with patch("intellisource.llm.gateway.litellm") as mock_litellm:
        mock_litellm.acompletion = AsyncMock(return_value=resp)
        gw = LLMGateway(cache=cache, cost_tracker=tracker)
        before = mc.get_labeled_counter_value(
            "llm_cache_hits_total", {"call_type": "chat"}
        )
        await gw.chat(
            messages=_MESSAGES,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        await gw.chat(
            messages=_MESSAGES,
            model="gpt-4o-mini",
            cache_key_parts={"call_type": "chat"},
        )
        after = mc.get_labeled_counter_value(
            "llm_cache_hits_total", {"call_type": "chat"}
        )

    assert after - before == 1.0
    statuses = [call.args[0].status for call in tracker.log_call.await_args_list]
    assert "cached" in statuses


def test_gateway_registers_cache_hits_metric() -> None:
    from intellisource.observability.metrics import MetricsCollector  # noqa: PLC0415

    LLMGateway()
    mc = MetricsCollector.get_instance()
    names = [name for name, _ in mc.iter_labeled_counters()]
    assert "llm_cache_hits_total" in names
