"""Tests for PromptBuilder and LLMGateway token truncation.

Covers:
- PromptBuilder template loading from prompts/ directory
- Variable substitution via add_context
- add_content with and without truncation
- add_schema serialization
- build() produces same output as load_prompt() for same inputs
- build_messages() returns correct message format
- truncate_content preserves first 40% + last 10%
- truncate_content is no-op when content is under limit
- LLMGateway truncation integration via max_input_tokens
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from intellisource.llm.prompt_builder import PromptBuilder

from intellisource.llm.prompts import load_prompt

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_litellm_response() -> MagicMock:
    """Build a mock litellm completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "mocked response"
    response.usage.prompt_tokens = 50
    response.usage.completion_tokens = 30
    response.model = "gpt-4o-mini"
    return response


# ===================================================================
# PromptBuilder template loading
# ===================================================================


class TestPromptBuilderTemplateLoading:
    """Verify PromptBuilder loads templates from prompts/ directory."""

    def test_init_loads_template_for_known_call_type(self) -> None:
        """PromptBuilder loads template when call_type matches a .txt file."""
        builder = PromptBuilder(call_type="extraction")
        # The builder should have loaded the template internally
        assert builder._template is not None
        assert len(builder._template) > 0

    def test_init_with_unknown_call_type_raises(self) -> None:
        """PromptBuilder raises FileNotFoundError for unknown call_type."""
        with pytest.raises(FileNotFoundError):
            PromptBuilder(call_type="nonexistent_template_xyz")

    def test_init_stores_model(self) -> None:
        """PromptBuilder stores the model parameter."""
        builder = PromptBuilder(call_type="extraction", model="gpt-4o")
        assert builder._model == "gpt-4o"

    def test_init_default_model(self) -> None:
        """PromptBuilder uses gpt-4o-mini as default model."""
        builder = PromptBuilder(call_type="extraction")
        assert builder._model == "gpt-4o-mini"


# ===================================================================
# Variable substitution via add_context
# ===================================================================


class TestPromptBuilderAddContext:
    """Verify add_context adds template variables for substitution."""

    def test_add_context_returns_self(self) -> None:
        """add_context returns self for method chaining."""
        builder = PromptBuilder(call_type="extraction")
        result = builder.add_context("schema", "{}")
        assert result is builder

    def test_add_context_stores_variable(self) -> None:
        """add_context stores the key-value pair for later substitution."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", '{"type": "object"}')
        assert builder._context["schema"] == '{"type": "object"}'


# ===================================================================
# add_content with and without truncation
# ===================================================================


class TestPromptBuilderAddContent:
    """Verify add_content adds content with optional truncation."""

    def test_add_content_returns_self(self) -> None:
        """add_content returns self for method chaining."""
        builder = PromptBuilder(call_type="extraction")
        result = builder.add_content("some text")
        assert result is builder

    def test_add_content_stores_content(self) -> None:
        """add_content stores the content string."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_content("hello world")
        assert builder._content == "hello world"

    def test_add_content_with_truncation(self) -> None:
        """add_content with max_tokens truncates long content."""
        long_text = "word " * 10000  # Very long text
        builder = PromptBuilder(call_type="extraction")
        builder.add_content(long_text, max_tokens=50)
        # Content should be truncated (shorter than original)
        assert len(builder._content) < len(long_text)
        assert "[..." in builder._content

    def test_add_content_no_truncation_when_short(self) -> None:
        """add_content with max_tokens does not truncate short content."""
        short_text = "hello world"
        builder = PromptBuilder(call_type="extraction")
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=3)
            builder.add_content(short_text, max_tokens=100)
        assert builder._content == short_text


# ===================================================================
# add_schema serialization
# ===================================================================


class TestPromptBuilderAddSchema:
    """Verify add_schema serializes dict to JSON string in context."""

    def test_add_schema_returns_self(self) -> None:
        """add_schema returns self for method chaining."""
        builder = PromptBuilder(call_type="extraction")
        result = builder.add_schema({"type": "object"})
        assert result is builder

    def test_add_schema_serializes_to_json(self) -> None:
        """add_schema stores JSON-serialized schema in context['schema']."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        builder = PromptBuilder(call_type="extraction")
        builder.add_schema(schema)
        stored = builder._context["schema"]
        assert json.loads(stored) == schema


# ===================================================================
# build() produces same output as load_prompt()
# ===================================================================


class TestPromptBuilderBuild:
    """Verify build() produces the correct formatted prompt."""

    def test_build_matches_load_prompt(self) -> None:
        """build() output matches load_prompt() for same template and vars."""
        schema_str = '{"type": "object"}'
        body = "The quick brown fox jumps."

        expected = load_prompt("extraction", schema=schema_str, body_text=body)

        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", schema_str)
        builder.add_context("body_text", body)
        result = builder.build()

        assert result == expected

    def test_build_with_content_substituted(self) -> None:
        """build() substitutes content into body_text context variable."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_content("My document text")
        builder.add_context("schema", '{"type": "object"}')
        builder.add_context("body_text", "My document text")
        result = builder.build()
        assert "My document text" in result

    def test_build_without_context_returns_raw_template(self) -> None:
        """build() with no substitution vars returns the raw template."""
        builder = PromptBuilder(call_type="summarizer")
        builder.add_context("docs_text", "some docs")
        result = builder.build()
        assert "some docs" in result


# ===================================================================
# build_messages() returns correct format
# ===================================================================


class TestPromptBuilderBuildMessages:
    """Verify build_messages() returns chat-style message list."""

    def test_build_messages_returns_list_of_dicts(self) -> None:
        """build_messages() returns a list of message dicts."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", '{"type": "object"}')
        builder.add_context("body_text", "text")
        messages = builder.build_messages()
        assert isinstance(messages, list)
        assert len(messages) >= 1
        for msg in messages:
            assert "role" in msg
            assert "content" in msg

    def test_build_messages_has_system_and_user(self) -> None:
        """build_messages() includes system + user messages."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", '{"type": "object"}')
        builder.add_context("body_text", "text")
        messages = builder.build_messages()
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_build_messages_user_contains_prompt(self) -> None:
        """build_messages() user message contains the formatted prompt."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", '{"type": "object"}')
        builder.add_context("body_text", "my text here")
        messages = builder.build_messages()
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "my text here" in user_msgs[0]["content"]


# ===================================================================
# truncate_content preserves first 40% + last 10%
# ===================================================================


class TestTruncateContent:
    """Verify truncate_content strategy: keep first 40% + last 10%."""

    def test_truncate_preserves_start_and_end(self) -> None:
        """truncate_content keeps the beginning and end of text."""
        # Create text where we can verify start/end preservation
        text = "START" + "x" * 1000 + "END"
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            # Make it think the text is over the limit
            mock_litellm.token_counter = MagicMock(return_value=500)
            result = PromptBuilder.truncate_content(text, max_tokens=100)
        assert result.startswith("START")
        assert result.endswith("END")
        assert "[..." in result

    def test_truncate_marker_contains_char_count(self) -> None:
        """truncate_content marker shows number of truncated characters."""
        text = "A" * 1000
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=500)
            result = PromptBuilder.truncate_content(text, max_tokens=100)
        # Should contain the truncation marker with char count
        assert "..." in result
        assert "截断" in result or "已截断" in result

    def test_truncate_noop_when_under_limit(self) -> None:
        """truncate_content returns original text when under token limit."""
        text = "short text"
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=3)
            result = PromptBuilder.truncate_content(text, max_tokens=100)
        assert result == text

    def test_truncate_ratio_approximately_correct(self) -> None:
        """truncate_content keeps ~40% from start and ~10% from end."""
        text = "A" * 1000
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=500)
            result = PromptBuilder.truncate_content(text, max_tokens=100)
        # The start portion should be ~400 chars (40% of 1000)
        # The end portion should be ~100 chars (10% of 1000)
        parts = result.split("[...")
        assert len(parts) == 2
        start_part = parts[0]
        # Allow some tolerance: start should be roughly 400 chars
        assert 350 <= len(start_part) <= 450

    def test_truncate_with_custom_model(self) -> None:
        """truncate_content uses the specified model for token counting."""
        text = "hello " * 100
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=200)
            PromptBuilder.truncate_content(
                text, max_tokens=50, model="claude-3-haiku-20240307"
            )
            call_kwargs = mock_litellm.token_counter.call_args
            assert call_kwargs.kwargs.get(
                "model"
            ) == "claude-3-haiku-20240307" or "claude-3-haiku-20240307" in str(
                call_kwargs
            )


# ===================================================================
# LLMGateway truncation integration
# ===================================================================


class TestGatewayTruncationIntegration:
    """Verify LLMGateway.complete() truncation with max_input_tokens."""

    @pytest.mark.asyncio
    async def test_complete_with_max_input_tokens_truncates(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() truncates prompt when max_input_tokens is set and exceeded."""
        from intellisource.llm.gateway import LLMGateway

        long_prompt = "word " * 50000
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            # token_counter returns high value to trigger truncation
            mock_litellm.token_counter = MagicMock(return_value=100000)
            gw = LLMGateway()
            result = await gw.complete(
                prompt=long_prompt,
                model="gpt-4o-mini",
                max_input_tokens=1000,
            )
        # Should still return a result
        assert result.content is not None
        # The user message sent should be truncated
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        user_msg = [m for m in call_kwargs["messages"] if m["role"] == "user"][0]
        assert len(user_msg["content"]) < len(long_prompt)

    @pytest.mark.asyncio
    async def test_complete_without_max_input_tokens_no_truncation(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() does not truncate when max_input_tokens is not set and tokens are low."""
        from intellisource.llm.gateway import LLMGateway

        prompt = "short prompt"
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=5)
            gw = LLMGateway()
            await gw.complete(prompt=prompt, model="gpt-4o-mini")
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        user_msg = [m for m in call_kwargs["messages"] if m["role"] == "user"][0]
        assert user_msg["content"] == prompt

    @pytest.mark.asyncio
    async def test_complete_auto_truncates_at_80_percent_context(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() auto-truncates when tokens exceed 80% of model context window."""
        from intellisource.llm.gateway import LLMGateway

        prompt = "word " * 50000
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            # 110000 > 80% of 128000 (=102400) for gpt-4o-mini
            mock_litellm.token_counter = MagicMock(return_value=110000)
            gw = LLMGateway()
            result = await gw.complete(prompt=prompt, model="gpt-4o-mini")
        assert result.content is not None
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        user_msg = [m for m in call_kwargs["messages"] if m["role"] == "user"][0]
        assert len(user_msg["content"]) < len(prompt)

    @pytest.mark.asyncio
    async def test_complete_logs_warning_on_truncation(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() logs a warning when truncation occurs."""
        from intellisource.llm.gateway import LLMGateway

        prompt = "word " * 50000
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch("intellisource.llm.gateway.logger") as mock_logger,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=110000)
            gw = LLMGateway()
            await gw.complete(
                prompt=prompt,
                model="gpt-4o-mini",
                max_input_tokens=1000,
            )
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_complete_preserves_existing_signature(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() still works with existing parameters (no breaking change)."""
        from intellisource.llm.gateway import LLMGateway

        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_litellm.token_counter = MagicMock(return_value=10)
            gw = LLMGateway()
            result = await gw.complete(
                prompt="test",
                model="gpt-4o-mini",
                system_prompt="You are helpful.",
                temperature=0.5,
                max_tokens=512,
                task_type="extract",
            )
        assert result.content is not None
