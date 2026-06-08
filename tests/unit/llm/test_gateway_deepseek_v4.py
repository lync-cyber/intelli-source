"""DeepSeek V4 adapter coverage (B-041).

Verifies:
- build_extra_body returns None for non-deepseek models
- thinking precedence: task_cfg > profile > deepseek-default-disabled
- reasoning_effort flows through
- chat()/complete()/stream_complete() inject extra_body into call_kwargs
- chat() captures message.reasoning_content into LLMResult.metadata
- FlexibleLoop appends reasoning_content onto multi-turn assistant message
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intellisource.agent.tools import PermissionLevel
from intellisource.llm.gateway import LLMGateway
from intellisource.llm.gateway._extra_body import (
    build_extra_body,
    extract_reasoning_content,
)
from intellisource.llm.gateway._routing import resolve_call_params
from intellisource.llm.model_config import ModelProfile, ModelRoutingConfig

# ---------------------------------------------------------------------------
# build_extra_body — pure function
# ---------------------------------------------------------------------------


class TestBuildExtraBody:
    def test_non_deepseek_returns_none(self) -> None:
        assert build_extra_body("gpt-4o-mini", None, None) is None
        assert build_extra_body("anthropic/claude-3", None, None) is None
        assert build_extra_body(None, None, None) is None

    def test_deepseek_default_thinking_disabled(self) -> None:
        out = build_extra_body("deepseek/deepseek-v4-flash", None, None)
        assert out == {"thinking": {"type": "disabled"}}

    def test_profile_thinking_wins_over_default(self) -> None:
        profile = ModelProfile(
            temperature=0.3,
            max_tokens=2048,
            context_window=100_000,
            thinking="enabled",
            reasoning_effort="high",
        )
        out = build_extra_body("deepseek/deepseek-v4-pro", None, profile)
        assert out == {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }

    def test_task_cfg_wins_over_profile(self) -> None:
        profile = ModelProfile(
            temperature=0.3,
            max_tokens=2048,
            context_window=100_000,
            thinking="enabled",
            reasoning_effort="max",
        )
        task_cfg: dict[str, Any] = {
            "thinking": "disabled",
            "reasoning_effort": "high",
        }
        out = build_extra_body("deepseek/deepseek-v4-pro", task_cfg, profile)
        assert out == {
            "thinking": {"type": "disabled"},
            "reasoning_effort": "high",
        }

    def test_reasoning_effort_only_when_set(self) -> None:
        out = build_extra_body(
            "deepseek/deepseek-v4-flash",
            {"thinking": "disabled"},
            None,
        )
        assert "reasoning_effort" not in out
        assert out["thinking"] == {"type": "disabled"}


# ---------------------------------------------------------------------------
# resolve_call_params — temperature/max_tokens precedence mirrors thinking:
# explicit caller arg > task_cfg (models[task]) > profile > gateway default
# ---------------------------------------------------------------------------


class TestResolveCallParamsPrecedence:
    @staticmethod
    def _routing() -> ModelRoutingConfig:
        return ModelRoutingConfig(
            {
                "default_model": {"model": "m", "provider": "p"},
                "models": {},
                "profiles": {
                    "m": {
                        "temperature": 0.1,
                        "max_tokens": 4096,
                        "context_window": 1000,
                    }
                },
            }
        )

    def test_task_cfg_wins_over_profile(self) -> None:
        _, temp, max_tokens = resolve_call_params(
            self._routing(),
            "m",
            None,
            None,
            0.7,
            256,
            task_cfg={"temperature": 0.0, "max_tokens": 512},
        )
        assert temp == 0.0
        assert max_tokens == 512

    def test_explicit_arg_wins_over_task_cfg(self) -> None:
        _, temp, max_tokens = resolve_call_params(
            self._routing(),
            "m",
            0.9,
            99,
            0.7,
            256,
            task_cfg={"temperature": 0.0, "max_tokens": 512},
        )
        assert temp == 0.9
        assert max_tokens == 99

    def test_profile_used_when_task_cfg_silent(self) -> None:
        _, temp, max_tokens = resolve_call_params(
            self._routing(), "m", None, None, 0.7, 256, task_cfg={}
        )
        assert temp == 0.1
        assert max_tokens == 4096

    def test_default_when_no_profile_no_task_cfg(self) -> None:
        routing = ModelRoutingConfig(
            {"default_model": {"model": "x", "provider": "p"}, "profiles": {}}
        )
        _, temp, max_tokens = resolve_call_params(
            routing, "x", None, None, 0.7, 256, task_cfg=None
        )
        assert temp == 0.7
        assert max_tokens == 256


# ---------------------------------------------------------------------------
# extract_reasoning_content
# ---------------------------------------------------------------------------


class TestExtractReasoningContent:
    def test_missing_attr_returns_none(self) -> None:
        msg = MagicMock(spec=[])  # no reasoning_content attr
        assert extract_reasoning_content(msg) is None

    def test_empty_string_returns_none(self) -> None:
        msg = MagicMock()
        msg.reasoning_content = ""
        assert extract_reasoning_content(msg) is None

    def test_returns_string(self) -> None:
        msg = MagicMock()
        msg.reasoning_content = "let me think step by step"
        assert extract_reasoning_content(msg) == "let me think step by step"

    def test_dict_message_supported(self) -> None:
        assert extract_reasoning_content({"reasoning_content": "x"}) == "x"
        assert extract_reasoning_content({"content": "y"}) is None

    def test_none_message(self) -> None:
        assert extract_reasoning_content(None) is None


# ---------------------------------------------------------------------------
# Gateway wiring — extra_body forwarded to litellm.acompletion
# ---------------------------------------------------------------------------


def _make_chat_response(content: str = "ok", reasoning: str | None = None) -> MagicMock:
    resp = MagicMock()
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    if reasoning is None:
        # ensure no attribute so getattr returns None
        del msg.reasoning_content
    else:
        msg.reasoning_content = reasoning
    resp.choices = [MagicMock(message=msg, finish_reason="stop")]
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.usage.__iter__ = lambda self: iter([])
    resp.model = "deepseek/deepseek-v4-flash"
    return resp


def _gateway_with_routing(routing: dict[str, Any]) -> LLMGateway:
    gw = LLMGateway()
    gw._routing_config = routing
    from intellisource.llm.model_config import ModelRoutingConfig

    gw._model_routing = ModelRoutingConfig(routing)
    return gw


class TestChatExtraBody:
    @pytest.mark.asyncio
    async def test_chat_injects_extra_body_for_deepseek(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routing = {
            "default_model": {
                "model": "deepseek/deepseek-v4-flash",
                "provider": "deepseek",
            },
            "models": {
                "chat": {
                    "model": "deepseek/deepseek-v4-flash",
                    "provider": "deepseek",
                    "thinking": "disabled",
                }
            },
            "profiles": {},
        }
        gw = _gateway_with_routing(routing)

        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.chat(messages=[{"role": "user", "content": "hi"}])

        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}

    @pytest.mark.asyncio
    async def test_chat_no_extra_body_for_openai(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routing = {
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
            "models": {
                "chat": {"model": "gpt-4o-mini", "provider": "openai"},
            },
            "profiles": {},
        }
        gw = _gateway_with_routing(routing)

        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.chat(messages=[{"role": "user", "content": "hi"}])

        assert "extra_body" not in captured

    @pytest.mark.asyncio
    async def test_chat_metadata_carries_reasoning_content(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routing = {
            "default_model": {
                "model": "deepseek/deepseek-v4-pro",
                "provider": "deepseek",
            },
            "models": {
                "chat": {
                    "model": "deepseek/deepseek-v4-pro",
                    "provider": "deepseek",
                    "thinking": "enabled",
                }
            },
            "profiles": {},
        }
        gw = _gateway_with_routing(routing)

        async def fake_acompletion(**kwargs: Any) -> Any:
            return _make_chat_response(content="final", reasoning="step1 step2")

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        result = await gw.chat(messages=[{"role": "user", "content": "go"}])
        assert result.content == "final"
        assert result.metadata["reasoning_content"] == "step1 step2"


class TestCompleteExtraBody:
    @pytest.mark.asyncio
    async def test_complete_injects_extra_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routing = {
            "default_model": {
                "model": "deepseek/deepseek-v4-flash",
                "provider": "deepseek",
            },
            "models": {
                "extract": {
                    "model": "deepseek/deepseek-v4-flash",
                    "provider": "deepseek",
                    "thinking": "disabled",
                }
            },
            "profiles": {},
        }
        gw = _gateway_with_routing(routing)

        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return _make_chat_response()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        await gw.complete(prompt="extract: foo", task_type="extract")

        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


class TestStreamExtraBody:
    @pytest.mark.asyncio
    async def test_stream_injects_extra_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        routing = {
            "default_model": {
                "model": "deepseek/deepseek-v4-flash",
                "provider": "deepseek",
            },
            "models": {
                "chat": {
                    "model": "deepseek/deepseek-v4-flash",
                    "provider": "deepseek",
                    "thinking": "disabled",
                }
            },
            "profiles": {},
        }
        gw = _gateway_with_routing(routing)

        captured: dict[str, Any] = {}

        async def fake_stream() -> AsyncIterator[Any]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "hello"
            chunk.usage = None
            chunk.model = "deepseek/deepseek-v4-flash"
            yield chunk

        async def fake_acompletion(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return fake_stream()

        monkeypatch.setattr(gw, "_acompletion", fake_acompletion)

        chunks: list[dict[str, Any]] = []
        async for c in gw.stream_complete(prompt="hi", task_type="chat"):
            chunks.append(c)

        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
        assert captured["stream"] is True


# ---------------------------------------------------------------------------
# FlexibleLoop multi-turn — assistant message preserves reasoning_content
# ---------------------------------------------------------------------------


class TestFlexibleReasoningRoundtrip:
    @pytest.mark.asyncio
    async def test_assistant_message_preserves_reasoning_content(
        self,
    ) -> None:
        from intellisource.agent.executors.flexible import FlexibleLoop
        from intellisource.llm.gateway._types import LLMResult

        # Reply turn 1: tool_call + reasoning_content. Turn 2: stop.
        result_turn1 = LLMResult(
            content="",
            metadata={
                "tool_calls": [
                    MagicMock(
                        function=MagicMock(name="search", arguments='{"q":"x"}'),
                        id="call_1",
                    )
                ],
                "finish_reason": "tool_calls",
                "model": "deepseek/deepseek-v4-pro",
                "usage": {
                    "total_tokens": 50,
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                },
                "reasoning_content": "I should search for x first.",
            },
        )
        # Make first tool_call.function.name come out right (MagicMock attr quirks)
        tc = result_turn1.metadata["tool_calls"][0]
        tc.function.name = "search"
        tc.function.arguments = '{"q":"x"}'

        result_turn2 = LLMResult(
            content="found it",
            metadata={
                "tool_calls": None,
                "finish_reason": "stop",
                "model": "deepseek/deepseek-v4-pro",
                "usage": {
                    "total_tokens": 60,
                    "prompt_tokens": 40,
                    "completion_tokens": 20,
                },
                "reasoning_content": None,
            },
        )

        chat_mock = AsyncMock(side_effect=[result_turn1, result_turn2])

        gateway = MagicMock()
        gateway.chat = chat_mock

        tool_def = MagicMock()
        tool_def.permission_level = PermissionLevel.auto
        tool_def.mutates_external_state = False
        tool_def.execute = AsyncMock(return_value={"hits": []})

        registry = MagicMock()
        registry.list_tools = MagicMock(return_value=["search"])
        registry.get = MagicMock(return_value=tool_def)

        async def _noop(*a: Any, **kw: Any) -> None:
            return None

        async def _persist(**kw: Any) -> dict[str, Any]:
            return {"status": kw.get("status", "")}

        loop = FlexibleLoop(
            tool_registry=registry,
            llm_gateway=gateway,
            emit_pipeline_start=_noop,
            emit_tool_call=_noop,
            emit_llm_call=_noop,
            emit_pipeline_error=_noop,
            persist=_persist,
        )

        config = MagicMock()
        config.name = "test"
        config.max_steps = 5
        config.tools_allowed = ["search"]
        config.tools_denied = []
        config.tool_permissions = {}
        config.system_prompt = None
        config.max_tokens_budget = None

        from intellisource.agent.runner import AgentMode

        await loop.run(
            config,
            user_message="please search",
            session={},
            agent_mode=AgentMode.process,
        )

        # Second chat() call must have received the assistant message with
        # reasoning_content roundtripped.
        second_messages = chat_mock.await_args_list[1].kwargs["messages"]
        assistant_messages = [m for m in second_messages if m["role"] == "assistant"]
        assert len(assistant_messages) == 1
        assert (
            assistant_messages[0]["reasoning_content"] == "I should search for x first."
        )
