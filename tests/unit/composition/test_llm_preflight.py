"""Tests for the chat-model function-calling preflight in build_llm_gateway."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from intellisource.composition.builders import _assert_chat_model_supports_tools
from intellisource.core.errors import CompositionError


class TestChatModelToolPreflight:
    """_assert_chat_model_supports_tools rejects an FC-incapable chat model."""

    def test_raises_when_chat_model_unsupported(self) -> None:
        cfg = {"models": {"chat": {"model": "foo/no-fc-model"}}}
        with patch(
            "intellisource.composition.builders.litellm.supports_function_calling",
            return_value=False,
        ):
            with pytest.raises(CompositionError, match="function calling"):
                _assert_chat_model_supports_tools(cfg)

    def test_does_not_raise_when_supported(self) -> None:
        cfg = {"models": {"chat": {"model": "deepseek/deepseek-v4-flash"}}}
        with patch(
            "intellisource.composition.builders.litellm.supports_function_calling",
            return_value=True,
        ):
            _assert_chat_model_supports_tools(cfg)

    def test_skips_when_no_chat_model_configured(self) -> None:
        _assert_chat_model_supports_tools({"models": {}})
