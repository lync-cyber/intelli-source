"""Tests for LLMGateway unified calling interface and SchemaEnforcer.

Covers:
- AC-028: LLMGateway.complete() unified call interface, supports any provider/model
- AC-031: SchemaEnforcer forces LLM output to conform to predefined JSON Schema
- AC-T019-1: Support configuring multiple LLM provider API keys via env vars
- AC-T019-2: Request parameter standardization (temperature/max_tokens/system_prompt)
- AC-T019-3: Call result includes input_tokens/output_tokens/latency_ms metadata
- AC-T019-4: JSON Schema validation failure raises SchemaValidationError
- AC-T019-5: LLMGateway.estimate_tokens(text, model) provides token counting
- AC-T019-6: task_type auto-selects model via config; fallback to default_model
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intellisource.core.errors import ErrorCategory, LLMError
from intellisource.llm.gateway import LLMGateway, SchemaEnforcer, SchemaValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "tags"],
}


@pytest.fixture
def mock_litellm_response() -> MagicMock:
    """Build a mock litellm completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(
        {"title": "Test", "tags": ["a", "b"]}
    )
    response.usage.prompt_tokens = 50
    response.usage.completion_tokens = 30
    response.model = "gpt-4o-mini"
    return response


@pytest.fixture
def gateway() -> LLMGateway:
    """Create an LLMGateway instance for testing."""
    return LLMGateway()


# ===================================================================
# AC-028: LLMGateway.complete() unified calling interface
# ===================================================================


class TestLLMGatewayComplete:
    """Verify LLMGateway.complete() provides a unified LLM calling interface."""

    @pytest.mark.asyncio
    async def test_complete_returns_result_with_content(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """complete() returns a result object containing generated content."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            result = await gateway.complete(
                prompt="Summarize this text",
                model="gpt-4o-mini",
            )
        assert result.content is not None
        assert isinstance(result.content, str)
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_complete_with_different_providers(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """complete() supports calling different provider/model combinations."""
        models = ["gpt-4o-mini", "claude-3-haiku-20240307", "deepseek/deepseek-chat"]
        for model in models:
            with patch("intellisource.llm.gateway.litellm") as mock_litellm:
                mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
                await gateway.complete(
                    prompt="Hello",
                    model=model,
                )
                # Verify litellm.acompletion was called with the correct model
                call_kwargs = mock_litellm.acompletion.call_args
                assert call_kwargs is not None
                assert model in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_complete_with_system_prompt(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """complete() passes system_prompt to the underlying LLM call."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await gateway.complete(
                prompt="Extract tags",
                model="gpt-4o-mini",
                system_prompt="You are a tagging assistant.",
            )
            call_kwargs = mock_litellm.acompletion.call_args
            messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get(
                "messages"
            )
            system_messages = [m for m in messages if m["role"] == "system"]
            assert len(system_messages) == 1
            assert system_messages[0]["content"] == "You are a tagging assistant."


# ===================================================================
# AC-T019-1: Multiple LLM provider API keys via environment variables
# ===================================================================


class TestAPIKeyConfiguration:
    """Verify API keys can be configured via environment variables."""

    @pytest.mark.asyncio
    async def test_openai_api_key_from_env(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """OpenAI API key is picked up from OPENAI_API_KEY env var."""
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-openai-key"}),
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            result = await gw.complete(prompt="test", model="gpt-4o-mini")
            assert json.loads(result.content) == {"title": "Test", "tags": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_anthropic_api_key_from_env(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """Anthropic API key is picked up from ANTHROPIC_API_KEY env var."""
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-anthropic-key"}),
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            result = await gw.complete(prompt="test", model="claude-3-haiku-20240307")
            assert json.loads(result.content) == {"title": "Test", "tags": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_multiple_providers_configured_simultaneously(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """Multiple provider keys can coexist in the environment."""
        env_vars = {
            "OPENAI_API_KEY": "sk-test-openai",
            "ANTHROPIC_API_KEY": "sk-test-anthropic",
            "IS_DEEPSEEK_API_KEY": "sk-test-deepseek",
        }
        with (
            patch.dict(os.environ, env_vars),
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            # Should be able to call with different providers without error
            result = await gw.complete(prompt="test", model="gpt-4o-mini")
            assert json.loads(result.content) == {"title": "Test", "tags": ["a", "b"]}


# ===================================================================
# AC-T019-2: Request parameter standardization
# ===================================================================


class TestRequestParameterStandardization:
    """Verify temperature/max_tokens/system_prompt are standardized."""

    @pytest.mark.asyncio
    async def test_temperature_parameter_passed_through(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """temperature parameter is forwarded to litellm."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await gateway.complete(prompt="test", model="gpt-4o-mini", temperature=0.7)
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs.get("temperature") == 0.7

    @pytest.mark.asyncio
    async def test_max_tokens_parameter_passed_through(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """max_tokens parameter is forwarded to litellm."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await gateway.complete(prompt="test", model="gpt-4o-mini", max_tokens=1024)
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs.get("max_tokens") == 1024

    @pytest.mark.asyncio
    async def test_default_parameters_applied(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """Default temperature and max_tokens are applied when not specified."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            await gateway.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            # Sensible defaults should be present
            assert "temperature" in call_kwargs
            assert "max_tokens" in call_kwargs


# ===================================================================
# AC-T019-3: Call result includes metadata
# ===================================================================


class TestCallResultMetadata:
    """Verify call results include input_tokens/output_tokens/latency_ms."""

    @pytest.mark.asyncio
    async def test_result_contains_input_tokens(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """Result metadata includes input_tokens count."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            result = await gateway.complete(prompt="test", model="gpt-4o-mini")
        assert hasattr(result, "metadata")
        assert result.metadata["input_tokens"] == 50

    @pytest.mark.asyncio
    async def test_result_contains_output_tokens(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """Result metadata includes output_tokens count."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            result = await gateway.complete(prompt="test", model="gpt-4o-mini")
        assert result.metadata["output_tokens"] == 30

    @pytest.mark.asyncio
    async def test_result_contains_latency_ms(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """Result metadata includes latency_ms measurement."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            result = await gateway.complete(prompt="test", model="gpt-4o-mini")
        assert "latency_ms" in result.metadata
        assert isinstance(result.metadata["latency_ms"], (int, float))
        assert result.metadata["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_result_contains_model_info(
        self, gateway: LLMGateway, mock_litellm_response: MagicMock
    ) -> None:
        """Result metadata includes the model identifier used."""
        with patch("intellisource.llm.gateway.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            result = await gateway.complete(prompt="test", model="gpt-4o-mini")
        assert result.metadata["model"] == "gpt-4o-mini"


# ===================================================================
# AC-031: SchemaEnforcer forces LLM output to conform to JSON Schema
# ===================================================================


class TestSchemaEnforcer:
    """Verify SchemaEnforcer validates LLM output against JSON Schema."""

    def test_valid_json_passes_validation(self) -> None:
        """Valid JSON conforming to schema passes without error."""
        enforcer = SchemaEnforcer(schema=SAMPLE_SCHEMA)
        valid_data = {"title": "Test Article", "tags": ["python", "llm"]}
        result = enforcer.validate(json.dumps(valid_data))
        assert result["title"] == "Test Article"
        assert result["tags"] == ["python", "llm"]

    def test_missing_required_field_raises_error(self) -> None:
        """Missing required field raises SchemaValidationError."""
        enforcer = SchemaEnforcer(schema=SAMPLE_SCHEMA)
        invalid_data = {"title": "Test Article"}  # missing 'tags'
        with pytest.raises(SchemaValidationError):
            enforcer.validate(json.dumps(invalid_data))

    def test_wrong_type_raises_error(self) -> None:
        """Wrong field type raises SchemaValidationError."""
        enforcer = SchemaEnforcer(schema=SAMPLE_SCHEMA)
        invalid_data = {"title": "Test", "tags": "not-an-array"}
        with pytest.raises(SchemaValidationError):
            enforcer.validate(json.dumps(invalid_data))

    def test_invalid_json_string_raises_error(self) -> None:
        """Non-JSON string raises SchemaValidationError."""
        enforcer = SchemaEnforcer(schema=SAMPLE_SCHEMA)
        with pytest.raises(SchemaValidationError):
            enforcer.validate("this is not json at all")


# ===================================================================
# AC-T019-4: SchemaValidationError inherits from LLMError
# ===================================================================


class TestSchemaValidationError:
    """Verify SchemaValidationError is properly defined."""

    def test_schema_validation_error_inherits_llm_error(self) -> None:
        """SchemaValidationError is a subclass of LLMError."""
        assert issubclass(SchemaValidationError, LLMError)

    def test_schema_validation_error_has_correct_category(self) -> None:
        """SchemaValidationError defaults to RECOVERABLE_DEGRADED category."""
        err = SchemaValidationError("test validation failure")
        assert err.category == ErrorCategory.RECOVERABLE_DEGRADED

    def test_schema_validation_error_message(self) -> None:
        """SchemaValidationError preserves the error message."""
        err = SchemaValidationError("field 'tags' is required")
        assert "tags" in str(err)


# ===================================================================
# AC-T019-5: LLMGateway.estimate_tokens() token counting
# ===================================================================


class TestEstimateTokens:
    """Verify LLMGateway.estimate_tokens() provides token counting."""

    def test_estimate_tokens_returns_integer(self, gateway: LLMGateway) -> None:
        """estimate_tokens() returns an integer count."""
        with patch("intellisource.llm.gateway._compaction.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=15)
            count = gateway.estimate_tokens(
                text="Hello, world! This is a test.", model="gpt-4o-mini"
            )
        assert isinstance(count, int)
        assert count > 0

    def test_estimate_tokens_uses_litellm_token_counter(
        self, gateway: LLMGateway
    ) -> None:
        """estimate_tokens() prefers litellm.token_counter when available."""
        with patch("intellisource.llm.gateway._compaction.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=42)
            count = gateway.estimate_tokens(
                text="Some sample text", model="gpt-4o-mini"
            )
            mock_litellm.token_counter.assert_called_once()
        assert count == 42

    def test_estimate_tokens_fallback_heuristic(self, gateway: LLMGateway) -> None:
        """estimate_tokens() falls back to heuristic when litellm fails."""
        with patch("intellisource.llm.gateway._compaction.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(
                side_effect=Exception("tokenizer not available")
            )
            count = gateway.estimate_tokens(
                text="Hello world this is a test sentence",
                model="unknown-model",
            )
        # Heuristic should still produce a reasonable positive integer
        assert isinstance(count, int)
        assert count > 0

    def test_estimate_tokens_empty_string(self, gateway: LLMGateway) -> None:
        """estimate_tokens() returns 0 for empty text."""
        with patch("intellisource.llm.gateway._compaction.litellm") as mock_litellm:
            mock_litellm.token_counter = MagicMock(return_value=0)
            count = gateway.estimate_tokens(text="", model="gpt-4o-mini")
        assert count == 0


# ===================================================================
# AC-T019-6: task_type parameter auto-selects model via config
# ===================================================================


class TestTaskTypeModelRouting:
    """Verify task_type-based model routing in LLMGateway.complete()."""

    @pytest.mark.asyncio
    async def test_complete_with_task_type_selects_model(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() with task_type uses model from config."""
        mock_config = {
            "models": {
                "extract": {"model": "gpt-4o-mini", "provider": "openai"},
                "summarize": {
                    "model": "claude-3-haiku-20240307",
                    "provider": "anthropic",
                },
            },
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
        }
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=mock_config,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="Extract entities", task_type="extract")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_complete_with_unknown_task_type_uses_default(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() with unknown task_type falls back to default_model."""
        mock_config = {
            "models": {
                "extract": {"model": "gpt-4o-mini", "provider": "openai"},
            },
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
        }
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=mock_config,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(
                prompt="Do something unknown", task_type="nonexistent_type"
            )
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_complete_with_unknown_task_type_logs_warning(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """complete() logs a WARNING when task_type has no matching config."""
        mock_config = {
            "models": {
                "extract": {"model": "gpt-4o-mini", "provider": "openai"},
            },
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
        }
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=mock_config,
            ),
            patch("intellisource.llm.gateway.logger") as mock_logger,
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", task_type="unknown_task")
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_model_overrides_task_type(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """When both model and task_type are provided, explicit model wins."""
        mock_config = {
            "models": {
                "extract": {"model": "gpt-4o-mini", "provider": "openai"},
            },
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
        }
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=mock_config,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(
                prompt="test",
                model="claude-3-haiku-20240307",
                task_type="extract",
            )
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["model"] == "claude-3-haiku-20240307"


# ===================================================================
# T-053: ModelProfile defaults applied in LLMGateway
# ===================================================================

_PROFILE_CONFIG = {
    "models": {
        "extract": {"model": "gpt-4o-mini", "provider": "openai"},
    },
    "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
    "profiles": {
        "gpt-4o-mini": {
            "temperature": 0.1,
            "max_tokens": 2048,
            "context_window": 128000,
            "prompt_style": "structured",
            "timeout_seconds": 30,
        },
    },
}


class TestModelProfileGatewayIntegration:
    """AC-T053-3/4/5/7: LLMGateway applies ModelProfile defaults."""

    @pytest.mark.asyncio
    async def test_profile_temperature_used_when_no_explicit(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-3: Gateway uses profile temperature when none given."""
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=_PROFILE_CONFIG,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_profile_max_tokens_used_when_no_explicit(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-4: Gateway uses profile max_tokens when none given."""
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=_PROFILE_CONFIG,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["max_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_explicit_temperature_overrides_profile(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-3: Explicit temperature overrides profile default."""
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=_PROFILE_CONFIG,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="gpt-4o-mini", temperature=0.9)
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs["temperature"] == 0.9

    @pytest.mark.asyncio
    async def test_unknown_model_fallback_to_gateway_defaults(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-5: Unknown model uses gateway built-in defaults."""
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=_PROFILE_CONFIG,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="some-unknown-model")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            # Should use gateway built-in defaults, not profile
            assert call_kwargs["temperature"] == gw._default_temperature
            assert call_kwargs["max_tokens"] == gw._default_max_tokens

    @pytest.mark.asyncio
    async def test_profile_timeout_applied_to_acompletion(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-7: Gateway passes timeout from profile to acompletion."""
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=_PROFILE_CONFIG,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert call_kwargs.get("timeout") == 30

    @pytest.mark.asyncio
    async def test_no_profile_no_timeout(
        self, mock_litellm_response: MagicMock
    ) -> None:
        """AC-T053-7: No profile means no explicit timeout in call."""
        config_no_profiles = {
            "models": {},
            "default_model": {"model": "gpt-4o-mini", "provider": "openai"},
        }
        with (
            patch("intellisource.llm.gateway.litellm") as mock_litellm,
            patch(
                "intellisource.llm.gateway._load_routing_config",
                return_value=config_no_profiles,
            ),
        ):
            mock_litellm.acompletion = AsyncMock(return_value=mock_litellm_response)
            gw = LLMGateway()
            await gw.complete(prompt="test", model="gpt-4o-mini")
            call_kwargs = mock_litellm.acompletion.call_args.kwargs
            assert "timeout" not in call_kwargs
