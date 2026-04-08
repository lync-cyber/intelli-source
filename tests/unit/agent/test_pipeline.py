"""Tests for PipelineConfig YAML/dict parsing and validation.

Covers:
- AC-066: PipelineConfig correctly parses YAML pipeline config
         (mode, tools_allowed/denied, steps, max_steps)
"""

from __future__ import annotations

import pytest
from intellisource.agent.pipeline import PipelineConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_STRICT_CONFIG: dict = {
    "name": "scheduled-collect",
    "mode": "strict",
    "steps": [
        {"tool": "rss_fetch", "params": {"url": "https://example.com/feed"}},
        {"tool": "html_clean", "params": {"selector": "article"}},
    ],
    "max_steps": 10,
    "on_failure": "abort",
}

FLEXIBLE_CONFIG: dict = {
    "name": "instant-search",
    "mode": "flexible",
    "tools_allowed": ["web_search", "summarize"],
    "tools_denied": ["file_delete", "db_drop"],
    "steps": [],
    "max_steps": 5,
    "on_failure": "skip",
}

STRICT_WITH_TOOLS_FILTER: dict = {
    "name": "filtered-pipeline",
    "mode": "strict",
    "tools_allowed": ["rss_fetch", "html_clean"],
    "tools_denied": ["dangerous_tool"],
    "steps": [
        {"tool": "rss_fetch", "params": {"url": "https://example.com"}},
    ],
    "max_steps": 20,
    "on_failure": "retry",
}


# ===================================================================
# AC-066: PipelineConfig correctly parses pipeline configuration
# ===================================================================


class TestPipelineConfigFromDict:
    """Verify PipelineConfig.from_dict parses all fields correctly."""

    def test_parse_strict_mode(self) -> None:
        """AC-066: strict mode is correctly parsed from dict."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.mode == "strict"

    def test_parse_name(self) -> None:
        """AC-066: pipeline name is preserved."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.name == "scheduled-collect"

    def test_parse_steps(self) -> None:
        """AC-066: steps list is correctly parsed with tool and params."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert len(config.steps) == 2
        assert config.steps[0]["tool"] == "rss_fetch"
        assert config.steps[1]["tool"] == "html_clean"

    def test_parse_max_steps(self) -> None:
        """AC-066: max_steps integer is preserved."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.max_steps == 10

    def test_parse_on_failure(self) -> None:
        """AC-066: on_failure strategy is preserved."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.on_failure == "abort"

    def test_parse_flexible_mode(self) -> None:
        """AC-066: flexible mode is correctly parsed."""
        config = PipelineConfig.from_dict(FLEXIBLE_CONFIG)
        assert config.mode == "flexible"

    def test_parse_tools_allowed(self) -> None:
        """AC-066: tools_allowed list is correctly parsed."""
        config = PipelineConfig.from_dict(FLEXIBLE_CONFIG)
        assert config.tools_allowed == ["web_search", "summarize"]

    def test_parse_tools_denied(self) -> None:
        """AC-066: tools_denied list is correctly parsed."""
        config = PipelineConfig.from_dict(FLEXIBLE_CONFIG)
        assert config.tools_denied == ["file_delete", "db_drop"]

    def test_default_tools_allowed_is_empty(self) -> None:
        """AC-066: tools_allowed defaults to empty list when absent."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.tools_allowed == []

    def test_default_tools_denied_is_empty(self) -> None:
        """AC-066: tools_denied defaults to empty list when absent."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.tools_denied == []


class TestPipelineConfigFromYaml:
    """Verify PipelineConfig.from_yaml loads from a YAML file."""

    def test_from_yaml_loads_valid_file(self, tmp_path) -> None:
        """AC-066: from_yaml reads and parses a YAML file."""
        import yaml

        yaml_path = tmp_path / "test-pipeline.yaml"
        yaml_path.write_text(yaml.dump(MINIMAL_STRICT_CONFIG), encoding="utf-8")
        config = PipelineConfig.from_yaml(str(yaml_path))
        assert config.name == "scheduled-collect"
        assert config.mode == "strict"
        assert len(config.steps) == 2


class TestPipelineConfigValidation:
    """Verify PipelineConfig rejects invalid configurations."""

    def test_invalid_mode_raises(self) -> None:
        """AC-066: mode must be 'strict' or 'flexible'."""
        bad = {**MINIMAL_STRICT_CONFIG, "mode": "turbo"}
        with pytest.raises((ValueError, KeyError)):
            PipelineConfig.from_dict(bad)

    def test_missing_name_raises(self) -> None:
        """AC-066: name is required."""
        bad = {k: v for k, v in MINIMAL_STRICT_CONFIG.items() if k != "name"}
        with pytest.raises((ValueError, KeyError)):
            PipelineConfig.from_dict(bad)

    def test_missing_steps_raises(self) -> None:
        """AC-066: steps is required."""
        bad = {k: v for k, v in MINIMAL_STRICT_CONFIG.items() if k != "steps"}
        with pytest.raises((ValueError, KeyError)):
            PipelineConfig.from_dict(bad)

    def test_invalid_on_failure_raises(self) -> None:
        """AC-066: on_failure must be retry/skip/abort."""
        bad = {**MINIMAL_STRICT_CONFIG, "on_failure": "explode"}
        with pytest.raises((ValueError, KeyError)):
            PipelineConfig.from_dict(bad)
