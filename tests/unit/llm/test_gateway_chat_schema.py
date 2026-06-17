"""Tests for F-09: chat() schema validation must be unconditional.

Verifies that SchemaEnforcer is called for all LLM responses when schema is
provided — not only when JSON is malformed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.llm.gateway import (
    LLMGateway,
    LLMOutputError,
    SchemaEnforcer,
)

_MESSAGES = [{"role": "user", "content": "hello"}]
_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _make_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].finish_reason = "stop"
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.model = "gpt-4o-mini"
    return resp


class TestF09SchemaValidationUnconditional:
    """F-09: SchemaEnforcer called unconditionally when schema is provided."""

    @pytest.mark.asyncio
    async def test_chat_schema_valid_json_valid_fields_passes(self) -> None:
        """Valid JSON matching schema returns LLMResult without raising."""
        gw = LLMGateway()
        resp = _make_response('{"name": "alice"}')

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            result = await gw.chat(messages=_MESSAGES, schema=_SCHEMA)

        assert result.content == '{"name": "alice"}'

    @pytest.mark.asyncio
    async def test_chat_schema_valid_json_invalid_fields_raises_llm_output_error(
        self,
    ) -> None:
        """Valid JSON but fields violating schema must raise LLMOutputError.

        Core coverage for F-09: valid JSON must not bypass schema validation.
        """
        gw = LLMGateway()
        # Valid JSON but 'name' field is missing (required by schema)
        resp = _make_response('{"age": 30}')

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            with pytest.raises(LLMOutputError, match="JSON validation"):
                await gw.chat(messages=_MESSAGES, schema=_SCHEMA)

    @pytest.mark.asyncio
    async def test_chat_schema_invalid_json_raises_llm_output_error(self) -> None:
        """Non-JSON content must raise LLMOutputError via SchemaEnforcer."""
        gw = LLMGateway()
        resp = _make_response("this is not json at all")

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            with pytest.raises(LLMOutputError, match="JSON validation"):
                await gw.chat(messages=_MESSAGES, schema=_SCHEMA)

    @pytest.mark.asyncio
    async def test_chat_schema_enforcer_always_called(self) -> None:
        """SchemaEnforcer.validate is called even when content is valid JSON."""
        gw = LLMGateway()
        resp = _make_response('{"name": "bob"}')

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            with patch.object(
                SchemaEnforcer, "validate", return_value={"name": "bob"}
            ) as spy:
                await gw.chat(messages=_MESSAGES, schema=_SCHEMA)
                spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_no_schema_skips_validation(self) -> None:
        """When schema=None, SchemaEnforcer is not instantiated."""
        gw = LLMGateway()
        resp = _make_response("plain text output")

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=resp)
            with patch.object(SchemaEnforcer, "validate") as spy:
                result = await gw.chat(messages=_MESSAGES, schema=None)
                spy.assert_not_called()
        assert result.content == "plain text output"
