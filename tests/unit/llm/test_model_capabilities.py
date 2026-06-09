"""Tests for first-party litellm model capability registration."""

from __future__ import annotations

import litellm

from intellisource.llm.model_capabilities import register_known_model_capabilities


class TestRegisterKnownModelCapabilities:
    """register_known_model_capabilities() makes deepseek v4 FC-capable in litellm."""

    def test_v4_flash_registered_as_function_calling_capable(self) -> None:
        register_known_model_capabilities()
        assert (
            litellm.supports_function_calling(model="deepseek/deepseek-v4-flash")
            is True
        )

    def test_v4_pro_registered_as_function_calling_capable(self) -> None:
        register_known_model_capabilities()
        assert (
            litellm.supports_function_calling(model="deepseek/deepseek-v4-pro") is True
        )
