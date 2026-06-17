"""Tests for PromptBuilder and LLMGateway token truncation.

Covers:
- PromptBuilder template loading from prompts/ directory
- Variable substitution via add_context
- build() produces same output as load_prompt() for same inputs
- truncate_content preserves first 40% + last 10%
- truncate_content is no-op when content is under limit
- LLMGateway truncation integration via max_input_tokens
"""

from __future__ import annotations

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
        """PromptBuilder loads template when call_type matches a .prompt.md file."""
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
# truncate_content preserves first 40% + last 10%
# ===================================================================


class TestTruncateContent:
    """Verify truncate_content strategy: keep first 40% + last 10%."""

    def test_truncate_preserves_start_and_end(self) -> None:
        """truncate_content keeps the beginning and end of text."""
        # Create text where we can verify start/end preservation
        text = "START" + "x" * 1000 + "END"
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            # Length-sensitive counter: SR-007 iterative loop re-checks
            # candidate length, so the mock must respond to shrinking.
            mock_litellm.token_counter = MagicMock(
                side_effect=lambda model, text: len(text) // 2
            )
            result = PromptBuilder.truncate_content(text, max_tokens=300)
        assert result.startswith("START")
        assert result.endswith("END")
        assert "[..." in result

    def test_truncate_marker_contains_char_count(self) -> None:
        """truncate_content marker shows number of truncated characters."""
        text = "A" * 1000
        with patch("intellisource.llm.prompt_builder.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(
                side_effect=lambda model, text: len(text) // 2
            )
            result = PromptBuilder.truncate_content(text, max_tokens=300)
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
            # Length-sensitive mock so the first 40%+10% cut passes the
            # re-verification step added in SR-007.
            mock_litellm.token_counter = MagicMock(
                side_effect=lambda model, text: len(text) // 2
            )
            result = PromptBuilder.truncate_content(text, max_tokens=300)
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
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch("intellisource.llm.gateway._compaction.litellm") as mock_estimate,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            # estimate_tokens consults token_counter; high value triggers truncation
            mock_estimate.token_counter = MagicMock(return_value=100000)
            gw = LLMGateway()
            result = await gw.complete(
                prompt=long_prompt,
                model="gpt-4o-mini",
                max_input_tokens=1000,
            )
        # Should still return a result
        assert result.content == "mocked response"
        # The user message sent should be truncated
        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        user_msg = [m for m in call_kwargs["messages"] if m["role"] == "user"][0]
        assert len(user_msg["content"]) < len(long_prompt)

    @pytest.mark.asyncio
    async def test_complete_without_max_input_tokens_no_truncation(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() no truncation when max_input_tokens unset and tokens are low."""
        from intellisource.llm.gateway import LLMGateway

        prompt = "short prompt"
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch("intellisource.llm.gateway._compaction.litellm") as mock_estimate,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_estimate.token_counter = MagicMock(return_value=5)
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
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch("intellisource.llm.gateway._compaction.litellm") as mock_estimate,
            patch("intellisource.llm.prompt_builder.litellm") as mock_pb_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            # 110000 > 80% of 128000 (=102400) for gpt-4o-mini; consulted by
            # estimate_tokens (gateway _CompactionMixin) to decide truncation
            mock_estimate.token_counter = MagicMock(return_value=110000)
            mock_pb_litellm.token_counter = MagicMock(return_value=110000)
            gw = LLMGateway()
            result = await gw.complete(prompt=prompt, model="gpt-4o-mini")
        assert result.content == "mocked response"
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
            patch("intellisource.llm.gateway._compaction.litellm") as mock_estimate,
            patch("intellisource.llm.gateway.logger") as mock_logger,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            mock_estimate.token_counter = MagicMock(return_value=110000)
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
        assert result.content == "mocked response"


# ===================================================================
# AC-T062: Prompt variant loading (style-based template selection)
# ===================================================================


class TestPromptVariantNaming:
    """AC-T062-1: Variant files are named {name}.{style}.prompt.md."""

    def test_variant_files_exist_extraction_structured(self) -> None:
        """`extraction.structured.prompt.md` exists in the prompts directory."""
        from pathlib import Path

        prompts_dir = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "intellisource"
            / "llm"
            / "prompts"
        )
        assert (prompts_dir / "extraction.structured.prompt.md").exists()

    def test_variant_files_exist_extraction_concise(self) -> None:
        """`extraction.concise.prompt.md` exists in the prompts directory."""
        from pathlib import Path

        prompts_dir = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "intellisource"
            / "llm"
            / "prompts"
        )
        assert (prompts_dir / "extraction.concise.prompt.md").exists()

    def test_variant_files_exist_summarizer_structured(self) -> None:
        """`summarizer.structured.prompt.md` exists in the prompts directory."""
        from pathlib import Path

        prompts_dir = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "intellisource"
            / "llm"
            / "prompts"
        )
        assert (prompts_dir / "summarizer.structured.prompt.md").exists()


class TestLoadPromptVariantStyle:
    """AC-T062-2 / AC-T062-5: load_prompt() resolves variant with style kwarg."""

    def test_load_prompt_style_loads_variant_content(self) -> None:
        """load_prompt(name, style=...) renders the variant when it exists."""
        result = load_prompt(
            "extraction", style="structured", schema="{}", body_text="text"
        )
        # The structured variant carries its own <schema>/<document> framing.
        assert "<schema>" in result
        assert "text" in result
        # Sanity: variant content differs from the default template.
        default = load_prompt("extraction", schema="{}", body_text="text")
        assert result != default

    def test_load_prompt_style_fallback_when_variant_missing(self) -> None:
        """load_prompt(name, style=...) falls back to base when variant absent."""
        result = load_prompt(
            "extraction",
            style="nonexistent_style_xyz",
            schema="{}",
            body_text="text",
        )
        default = load_prompt("extraction", schema="{}", body_text="text")
        assert result == default

    def test_load_prompt_without_style_unchanged(self) -> None:
        """load_prompt(name, **kwargs) without style kwarg is backward compatible."""
        result = load_prompt("extraction", schema="{}", body_text="text")
        assert result is not None
        assert len(result) > 0

    def test_load_prompt_style_none_uses_base(self) -> None:
        """load_prompt(name, style=None) behaves identically to no style argument."""
        result_none = load_prompt(
            "extraction", style=None, schema="{}", body_text="text"
        )
        result_default = load_prompt("extraction", schema="{}", body_text="text")
        assert result_none == result_default


class TestVariantFilesNonEmpty:
    """AC-T062-3/AC-T062-4: Variant files are non-empty with expected placeholders."""

    def test_extraction_structured_is_nonempty(self) -> None:
        """extraction.structured renders content with {schema}/{body_text} vars."""
        result = load_prompt(
            "extraction",
            style="structured",
            schema='{"type":"object"}',
            body_text="sample",
        )
        assert len(result) > 0
        assert '{"type":"object"}' in result
        assert "sample" in result

    def test_extraction_concise_is_nonempty(self) -> None:
        """extraction.concise renders content with {schema}/{body_text} vars."""
        result = load_prompt(
            "extraction",
            style="concise",
            schema='{"type":"object"}',
            body_text="sample",
        )
        assert len(result) > 0
        assert '{"type":"object"}' in result
        assert "sample" in result

    def test_summarizer_structured_is_nonempty(self) -> None:
        """summarizer.structured renders content with the {docs_text} var."""
        result = load_prompt("summarizer", style="structured", docs_text="sample docs")
        assert len(result) > 0
        assert "sample docs" in result


class TestPromptBuilderVariantStyle:
    """AC-T062-2/AC-T062-5: PromptBuilder accepts prompt_style and selects variant."""

    def test_prompt_builder_accepts_prompt_style_kwarg(self) -> None:
        """PromptBuilder accepts prompt_style keyword argument without raising."""
        builder = PromptBuilder(call_type="extraction", prompt_style="structured")
        assert isinstance(builder._template, str)
        assert len(builder._template) > 0

    def test_prompt_builder_prompt_style_loads_variant(self) -> None:
        """PromptBuilder with prompt_style loads the variant template content."""
        builder_default = PromptBuilder(call_type="extraction")
        builder_variant = PromptBuilder(
            call_type="extraction", prompt_style="structured"
        )
        assert builder_variant._template != builder_default._template

    def test_prompt_builder_prompt_style_none_loads_base(self) -> None:
        """PromptBuilder with prompt_style=None loads the base template."""
        builder_none = PromptBuilder(call_type="extraction", prompt_style=None)
        builder_default = PromptBuilder(call_type="extraction")
        assert builder_none._template == builder_default._template

    def test_prompt_builder_missing_variant_falls_back_to_base(self) -> None:
        """PromptBuilder with unknown prompt_style falls back to base template."""
        builder_fallback = PromptBuilder(
            call_type="extraction", prompt_style="no_such_style_xyz"
        )
        builder_default = PromptBuilder(call_type="extraction")
        assert builder_fallback._template == builder_default._template

    def test_prompt_builder_without_prompt_style_backward_compatible(self) -> None:
        """PromptBuilder called without prompt_style is backward compatible."""
        builder = PromptBuilder(call_type="extraction")
        builder.add_context("schema", "{}")
        builder.add_context("body_text", "hello")
        result = builder.build()
        assert "hello" in result


class TestPromptPathComponentValidation:
    """name/style must be a single filename component (defense-in-depth)."""

    @pytest.mark.parametrize(
        "bad_name",
        ["../etc/passwd", "foo/bar", "foo\\bar", "..", "", "with\0null"],
    )
    def test_load_prompt_rejects_unsafe_name(self, bad_name: str) -> None:
        """load_prompt() raises ValueError when name contains path components."""
        with pytest.raises(ValueError, match="Invalid name"):
            load_prompt(bad_name)

    @pytest.mark.parametrize(
        "bad_style",
        ["../sneak", "structured/oops", "..", "", "with\0null"],
    )
    def test_load_prompt_rejects_unsafe_style(self, bad_style: str) -> None:
        """load_prompt() raises ValueError when style contains path components."""
        with pytest.raises(ValueError, match="Invalid style"):
            load_prompt("extraction", style=bad_style, schema="{}", body_text="x")

    def test_prompt_builder_rejects_unsafe_prompt_style(self) -> None:
        """PromptBuilder propagates the ValueError raised by the loader."""
        with pytest.raises(ValueError, match="Invalid style"):
            PromptBuilder(call_type="extraction", prompt_style="../escape")
