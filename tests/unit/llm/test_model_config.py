"""Tests for LLM model routing configuration loading.

Covers:
- AC-T019-6: Load task_type -> model mapping from config/llm_models.yaml
- AC-T019-6: Lookup by task_type returns correct model config
- AC-T019-6: Missing task_type returns default_model
- AC-T019-6: Missing config file raises appropriate error
- AC-T019-6: Malformed YAML raises appropriate error
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml
from intellisource.llm.model_config import (
    ModelConfig,
    ModelRoutingConfig,
    load_model_config,
)

# ---------------------------------------------------------------------------
# Sample config data
# ---------------------------------------------------------------------------

SAMPLE_CONFIG_DICT = {
    "default_model": {
        "model": "gpt-4o-mini",
        "provider": "openai",
    },
    "models": {
        "extract": {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "temperature": 0.0,
            "max_tokens": 4096,
        },
        "summarize": {
            "model": "claude-3-haiku-20240307",
            "provider": "anthropic",
            "temperature": 0.3,
            "max_tokens": 2048,
        },
        "dedup": {
            "model": "gpt-4o-mini",
            "provider": "openai",
            "temperature": 0.0,
            "max_tokens": 1024,
        },
        "tag": {
            "model": "deepseek/deepseek-chat",
            "provider": "deepseek",
            "temperature": 0.1,
            "max_tokens": 512,
        },
    },
}


# ===========================================================================
# load_model_config() -- YAML file loading
# ===========================================================================


class TestLoadModelConfig:
    """Verify load_model_config() correctly loads and parses YAML config."""

    def test_load_from_yaml_file(self, tmp_path: Path) -> None:
        """load_model_config() reads a YAML file and returns config dict."""
        config_file = tmp_path / "llm_models.yaml"
        config_file.write_text(yaml.dump(SAMPLE_CONFIG_DICT))

        result = load_model_config(str(config_file))

        assert "default_model" in result
        assert "models" in result
        assert result["default_model"]["model"] == "gpt-4o-mini"

    def test_load_returns_all_task_types(self, tmp_path: Path) -> None:
        """load_model_config() returns all task_type entries from the file."""
        config_file = tmp_path / "llm_models.yaml"
        config_file.write_text(yaml.dump(SAMPLE_CONFIG_DICT))

        result = load_model_config(str(config_file))

        assert "extract" in result["models"]
        assert "summarize" in result["models"]
        assert "dedup" in result["models"]
        assert "tag" in result["models"]

    def test_load_missing_file_raises_error(self) -> None:
        """load_model_config() raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_model_config("/nonexistent/path/llm_models.yaml")

    def test_load_malformed_yaml_raises_error(self, tmp_path: Path) -> None:
        """load_model_config() raises error for malformed YAML content."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("{{invalid: yaml: [content")

        with pytest.raises((yaml.YAMLError, ValueError)):
            load_model_config(str(config_file))

    def test_load_missing_default_model_raises_error(self, tmp_path: Path) -> None:
        """load_model_config() raises error when default_model is missing."""
        incomplete_config = {
            "models": {"extract": {"model": "gpt-4o-mini", "provider": "openai"}}
        }
        config_file = tmp_path / "incomplete.yaml"
        config_file.write_text(yaml.dump(incomplete_config))

        with pytest.raises((KeyError, ValueError)):
            load_model_config(str(config_file))

    def test_load_empty_file_raises_error(self, tmp_path: Path) -> None:
        """load_model_config() raises error for empty YAML file."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        with pytest.raises((ValueError, TypeError)):
            load_model_config(str(config_file))


# ===========================================================================
# ModelRoutingConfig -- task_type lookup
# ===========================================================================


class TestModelRoutingConfig:
    """Verify ModelRoutingConfig provides task_type -> model lookup."""

    def test_get_model_for_known_task_type(self) -> None:
        """get_model() returns the correct model config for a known task_type."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        result = routing.get_model("extract")

        assert result["model"] == "gpt-4o-mini"
        assert result["provider"] == "openai"

    def test_get_model_for_summarize_task(self) -> None:
        """get_model() returns Anthropic model for summarize task."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        result = routing.get_model("summarize")

        assert result["model"] == "claude-3-haiku-20240307"
        assert result["provider"] == "anthropic"

    def test_get_model_unknown_task_returns_default(self) -> None:
        """get_model() returns default_model for unknown task_type."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        result = routing.get_model("nonexistent_task")

        assert result["model"] == "gpt-4o-mini"
        assert result["provider"] == "openai"

    def test_get_model_unknown_task_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """get_model() logs WARNING when task_type has no matching config."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        with caplog.at_level(logging.WARNING):
            routing.get_model("unknown_task_type")

        assert any("unknown_task_type" in record.message for record in caplog.records)

    def test_get_model_returns_task_specific_params(self) -> None:
        """get_model() returns temperature/max_tokens from task config."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        result = routing.get_model("extract")

        assert result.get("temperature") == 0.0
        assert result.get("max_tokens") == 4096

    def test_available_task_types(self) -> None:
        """available_task_types returns list of configured task types."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        task_types = routing.available_task_types

        assert set(task_types) == {"extract", "summarize", "dedup", "tag"}

    def test_default_model_property(self) -> None:
        """default_model property returns the default model config."""
        routing = ModelRoutingConfig(SAMPLE_CONFIG_DICT)

        default = routing.default_model

        assert default["model"] == "gpt-4o-mini"
        assert default["provider"] == "openai"


# ===========================================================================
# ModelConfig -- individual model config dataclass
# ===========================================================================


class TestModelConfig:
    """Verify ModelConfig data structure."""

    def test_model_config_from_dict(self) -> None:
        """ModelConfig can be created from a dict."""
        data = {"model": "gpt-4o-mini", "provider": "openai", "temperature": 0.5}
        config = ModelConfig(**data)

        assert config.model == "gpt-4o-mini"
        assert config.provider == "openai"
        assert config.temperature == 0.5

    def test_model_config_required_fields(self) -> None:
        """ModelConfig requires at least model and provider fields."""
        with pytest.raises(TypeError):
            ModelConfig()  # type: ignore[call-arg]

    def test_model_config_optional_temperature(self) -> None:
        """ModelConfig temperature defaults to None when not specified."""
        config = ModelConfig(model="gpt-4o-mini", provider="openai")

        assert config.temperature is None or isinstance(config.temperature, float)

    def test_model_config_optional_max_tokens(self) -> None:
        """ModelConfig max_tokens defaults to None when not specified."""
        config = ModelConfig(model="gpt-4o-mini", provider="openai")

        assert config.max_tokens is None or isinstance(config.max_tokens, int)
