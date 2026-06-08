"""Tests for PipelineConfig YAML/dict parsing and validation.

Covers:
- AC-066: PipelineConfig correctly parses YAML pipeline config
         (mode, tools_allowed/denied, steps, max_steps)
"""

from __future__ import annotations

import pytest

from intellisource.config.pipeline_models import PipelineConfig

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


# ===================================================================
# T-055: Pipeline config updates + system_prompt parsing
# ===================================================================


class TestSystemPromptParsing:
    """AC-T055-3: PipelineConfig parses system_prompt field."""

    def test_system_prompt_parsed_from_dict(self) -> None:
        """AC-T055-3: system_prompt is parsed when present."""
        data = {**FLEXIBLE_CONFIG, "system_prompt": "You are a helper."}
        config = PipelineConfig.from_dict(data)
        assert config.system_prompt == "You are a helper."

    def test_system_prompt_defaults_to_none(self) -> None:
        """AC-T055-3: system_prompt defaults to None when absent."""
        config = PipelineConfig.from_dict(MINIMAL_STRICT_CONFIG)
        assert config.system_prompt is None


class TestUpdatedPipelineConfigs:
    """AC-T055-1/2/4: Updated pipeline YAML configs."""

    def test_scheduled_collect_uses_atomic_tools(self) -> None:
        """AC-T055-1: scheduled-collect tools_allowed includes atomic tools."""
        from intellisource.pipeline.definition_service import load_pipeline_config

        config = load_pipeline_config("scheduled-collect")
        allowed = set(config.tools_allowed)
        assert "collect" in allowed
        assert "distribute" in allowed
        # Should include atomic processing tools instead of generic "process"
        assert "regex_extract" in allowed or "fingerprint_generate" in allowed

    def test_instant_search_includes_atomic_tools(self) -> None:
        """AC-T055-2: instant-search tools_allowed includes atomic tools."""
        from intellisource.pipeline.definition_service import load_pipeline_config

        config = load_pipeline_config("instant-search")
        allowed = set(config.tools_allowed)
        assert "search" in allowed
        assert "get_content_detail" in allowed
        assert "summarize_for_user" in allowed
        # Should also include relevant atomic tools
        assert "tfidf_keywords" in allowed or "summarize_cluster" in allowed

    def test_existing_pipeline_configs_parse(self) -> None:
        """AC-T055-4: All pipeline configs parse without error."""
        from intellisource.pipeline.definition_service import load_pipeline_config

        for name in [
            "scheduled-collect",
            "manual-collect",
            "instant-search",
            "content-process",
            "push-optimize",
        ]:
            config = load_pipeline_config(name)
            assert config.name == name
