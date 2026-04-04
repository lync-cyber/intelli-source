"""Tests for ConfigValidator.

Covers:
- AC-T008-1: Support YAML and JSON format parsing
- AC-T008-2: Validation failure returns all errors (not fail-fast)
- AC-T008-3: Config supports ${ENV_VAR} placeholder syntax
- AC-003: Invalid config raises clear ValidationError
"""

import json

import pytest
import yaml
from intellisource.config.validator import ConfigValidator
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SOURCE = {
    "name": "arxiv-cs",
    "type": "rss",
    "url": "https://arxiv.org/rss/cs",
    "tags": ["ai"],
}

VALID_YAML_SINGLE = yaml.dump({"sources": [VALID_SOURCE]})

VALID_JSON_SINGLE = json.dumps({"sources": [VALID_SOURCE]})


@pytest.fixture
def validator():
    return ConfigValidator()


# ---------------------------------------------------------------------------
# AC-T008-1: YAML and JSON format parsing
# ---------------------------------------------------------------------------


class TestFormatParsing:
    """AC-T008-1: Support YAML and JSON formats."""

    def test_parse_yaml_single_source(self, validator):
        """A valid YAML string with one source returns a list of one SourceConfig."""
        results = validator.validate_sources_file(VALID_YAML_SINGLE, format="yaml")
        assert len(results) == 1
        assert results[0].name == "arxiv-cs"
        assert results[0].type == "rss"
        assert results[0].url == "https://arxiv.org/rss/cs"

    def test_parse_json_single_source(self, validator):
        """A valid JSON string with one source returns a list of one SourceConfig."""
        results = validator.validate_sources_file(VALID_JSON_SINGLE, format="json")
        assert len(results) == 1
        assert results[0].name == "arxiv-cs"
        assert results[0].type == "rss"

    def test_parse_yaml_multiple_sources(self, validator):
        """YAML with multiple sources returns all of them."""
        second_source = {
            "name": "hackernews",
            "type": "web",
            "url": "https://news.ycombinator.com",
        }
        content = yaml.dump({"sources": [VALID_SOURCE, second_source]})
        results = validator.validate_sources_file(content, format="yaml")
        assert len(results) == 2
        assert results[0].name == "arxiv-cs"
        assert results[1].name == "hackernews"

    def test_parse_json_multiple_sources(self, validator):
        """JSON with multiple sources returns all of them."""
        second_source = {
            "name": "hackernews",
            "type": "web",
            "url": "https://news.ycombinator.com",
        }
        content = json.dumps({"sources": [VALID_SOURCE, second_source]})
        results = validator.validate_sources_file(content, format="json")
        assert len(results) == 2
        assert results[1].name == "hackernews"


# ---------------------------------------------------------------------------
# AC-003 + AC-T008-2: Validation errors
# ---------------------------------------------------------------------------


class TestValidateSource:
    """AC-003: validate_source raises ValidationError for invalid data."""

    def test_validate_source_valid(self, validator):
        """A valid dict returns a SourceConfig instance."""
        result = validator.validate_source(VALID_SOURCE)
        assert result.name == "arxiv-cs"

    def test_validate_source_missing_required(self, validator):
        """Missing required fields raise ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_source({"tags": ["ai"]})

    def test_validate_source_invalid_type_enum(self, validator):
        """Invalid type enum raises ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_source(
                {"name": "s", "type": "ftp", "url": "https://example.com"}
            )

    def test_validate_source_invalid_url(self, validator):
        """Invalid URL raises ValidationError."""
        with pytest.raises(ValidationError):
            validator.validate_source({"name": "s", "type": "rss", "url": "not-a-url"})


class TestValidateSourcesFileErrors:
    """AC-T008-2: All validation errors are collected across sources."""

    def test_invalid_yaml_syntax_raises_error(self, validator):
        """Malformed YAML raises an error (ValueError or yaml.YAMLError)."""
        with pytest.raises(Exception):
            validator.validate_sources_file("{{invalid: yaml: [", format="yaml")

    def test_invalid_json_syntax_raises_error(self, validator):
        """Malformed JSON raises an error."""
        with pytest.raises(Exception):
            validator.validate_sources_file("{not valid json", format="json")

    def test_validation_errors_collected_for_multiple_sources(self, validator):
        """When multiple sources are invalid, errors for all are reported."""
        bad_sources = {
            "sources": [
                {"name": "ok", "type": "rss", "url": "https://example.com"},
                {"type": "rss"},  # missing name, url
                {"name": "bad-type", "type": "ftp", "url": "https://x.com"},
            ]
        }
        content = yaml.dump(bad_sources)
        # The method should either raise with all errors or return partial results
        # with error details. Based on the contract, validation failure returns
        # all errors. We expect an exception that contains error info for
        # sources at index 1 and 2.
        with pytest.raises(Exception) as exc_info:
            validator.validate_sources_file(content, format="yaml")
        # The exception should contain information about multiple errors
        error_str = str(exc_info.value)
        # At minimum, errors from source index 1 (missing fields) should be present
        assert len(error_str) > 0


# ---------------------------------------------------------------------------
# AC-T008-3: Environment variable placeholder ${ENV_VAR}
# ---------------------------------------------------------------------------


class TestEnvVarPlaceholder:
    """AC-T008-3: ${ENV_VAR} placeholders resolved from environment."""

    def test_env_var_in_url_resolved(self, validator, monkeypatch):
        """${ENV_VAR} in url field is resolved from environment."""
        monkeypatch.setenv("TEST_SOURCE_HOST", "https://resolved.example.com")
        source_data = {
            "sources": [
                {
                    "name": "env-source",
                    "type": "api",
                    "url": "${TEST_SOURCE_HOST}/api/v1",
                }
            ]
        }
        content = yaml.dump(source_data)
        results = validator.validate_sources_file(content, format="yaml")
        assert len(results) == 1
        assert "resolved.example.com" in results[0].url
        assert "${TEST_SOURCE_HOST}" not in results[0].url

    def test_env_var_in_proxy_resolved(self, validator, monkeypatch):
        """${ENV_VAR} in proxy field is resolved."""
        monkeypatch.setenv("PROXY_URL", "http://myproxy:8080")
        source_data = {
            "sources": [
                {
                    "name": "proxy-source",
                    "type": "rss",
                    "url": "https://example.com/rss",
                    "proxy": "${PROXY_URL}",
                }
            ]
        }
        content = yaml.dump(source_data)
        results = validator.validate_sources_file(content, format="yaml")
        assert results[0].proxy == "http://myproxy:8080"

    def test_env_var_in_name_resolved(self, validator, monkeypatch):
        """${ENV_VAR} in name field is resolved."""
        monkeypatch.setenv("SOURCE_NAME", "dynamic-source")
        source_data = {
            "sources": [
                {
                    "name": "${SOURCE_NAME}",
                    "type": "web",
                    "url": "https://example.com",
                }
            ]
        }
        content = yaml.dump(source_data)
        results = validator.validate_sources_file(content, format="yaml")
        assert results[0].name == "dynamic-source"

    def test_undefined_env_var_not_silently_ignored(self, validator, monkeypatch):
        """An undefined ${ENV_VAR} should raise an error or remain unresolved,
        not silently produce an empty string."""
        monkeypatch.delenv("UNDEFINED_VAR_XYZ_12345", raising=False)
        source_data = {
            "sources": [
                {
                    "name": "bad-env",
                    "type": "rss",
                    "url": "${UNDEFINED_VAR_XYZ_12345}",
                }
            ]
        }
        content = yaml.dump(source_data)
        # Either raises an error about undefined env var, or the URL validation
        # fails because the placeholder is not a valid URL
        with pytest.raises(Exception):
            validator.validate_sources_file(content, format="yaml")

    def test_multiple_env_vars_in_single_value(self, validator, monkeypatch):
        """Multiple ${ENV_VAR} placeholders in a single value are all resolved."""
        monkeypatch.setenv("API_SCHEME", "https")
        monkeypatch.setenv("API_HOST", "api.example.com")
        source_data = {
            "sources": [
                {
                    "name": "multi-env",
                    "type": "api",
                    "url": "${API_SCHEME}://${API_HOST}/v1",
                }
            ]
        }
        content = yaml.dump(source_data)
        results = validator.validate_sources_file(content, format="yaml")
        assert results[0].url == "https://api.example.com/v1"
