"""Tests for SourceConfig Pydantic model.

Covers:
- AC-001: SourceConfig field definitions (name/type/url/tags/schedule/proxy/rate_limit)
- AC-003: Invalid config raises ValidationError with clear messages
- AC-T008-2: Validation collects all errors (not fail-fast)
"""

import pytest
from intellisource.config.models import SourceConfig
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# AC-001: SourceConfig field definitions
# ---------------------------------------------------------------------------


class TestSourceConfigRequiredFields:
    """AC-001: Required fields -- name, type, url."""

    def test_valid_minimal_config(self):
        """A config with only required fields should produce a valid model."""
        config = SourceConfig.model_validate(
            {"name": "arxiv-cs", "type": "rss", "url": "https://arxiv.org/rss/cs"}
        )
        assert config.name == "arxiv-cs"
        assert config.type == "rss"
        assert config.url == "https://arxiv.org/rss/cs"

    def test_type_enum_rss(self):
        """type='rss' is accepted."""
        config = SourceConfig.model_validate(
            {"name": "feed", "type": "rss", "url": "https://example.com/rss"}
        )
        assert config.type == "rss"

    def test_type_enum_api(self):
        """type='api' is accepted."""
        config = SourceConfig.model_validate(
            {"name": "api-source", "type": "api", "url": "https://api.example.com/v1"}
        )
        assert config.type == "api"

    def test_type_enum_web(self):
        """type='web' is accepted."""
        config = SourceConfig.model_validate(
            {"name": "web-source", "type": "web", "url": "https://example.com"}
        )
        assert config.type == "web"


class TestSourceConfigOptionalFields:
    """AC-001: Optional fields with defaults."""

    def test_tags_default_empty_list(self):
        """tags defaults to an empty list."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.tags == []

    def test_tags_with_values(self):
        """tags accepts a list of strings."""
        config = SourceConfig.model_validate(
            {
                "name": "s",
                "type": "rss",
                "url": "https://example.com",
                "tags": ["ai", "ml"],
            }
        )
        assert config.tags == ["ai", "ml"]

    def test_schedule_interval_default(self):
        """schedule_interval defaults to 3600."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.schedule_interval == 3600

    def test_schedule_adaptive_default_true(self):
        """schedule_adaptive defaults to True."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.schedule_adaptive is True

    def test_proxy_default_none(self):
        """proxy defaults to None."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.proxy is None

    def test_proxy_with_value(self):
        """proxy accepts a string value."""
        config = SourceConfig.model_validate(
            {
                "name": "s",
                "type": "rss",
                "url": "https://example.com",
                "proxy": "http://proxy:8080",
            }
        )
        assert config.proxy == "http://proxy:8080"

    def test_rate_limit_qps_default_none(self):
        """rate_limit_qps defaults to None."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.rate_limit_qps is None

    def test_rate_limit_concurrency_default_none(self):
        """rate_limit_concurrency defaults to None."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.rate_limit_concurrency is None

    def test_metadata_default_empty_dict(self):
        """metadata defaults to an empty dict."""
        config = SourceConfig.model_validate(
            {"name": "s", "type": "rss", "url": "https://example.com"}
        )
        assert config.metadata == {}

    def test_full_config_all_fields(self):
        """A config with all fields explicitly set should be valid."""
        data = {
            "name": "full-source",
            "type": "api",
            "url": "https://api.example.com/v2",
            "tags": ["science", "tech"],
            "schedule_interval": 1800,
            "schedule_adaptive": False,
            "proxy": "socks5://proxy:1080",
            "rate_limit_qps": 2.5,
            "rate_limit_concurrency": 4,
            "metadata": {"auth": "bearer"},
        }
        config = SourceConfig.model_validate(data)
        assert config.name == "full-source"
        assert config.type == "api"
        assert config.url == "https://api.example.com/v2"
        assert config.tags == ["science", "tech"]
        assert config.schedule_interval == 1800
        assert config.schedule_adaptive is False
        assert config.proxy == "socks5://proxy:1080"
        assert config.rate_limit_qps == 2.5
        assert config.rate_limit_concurrency == 4
        assert config.metadata == {"auth": "bearer"}


# ---------------------------------------------------------------------------
# AC-003: Invalid config raises ValidationError
# ---------------------------------------------------------------------------


class TestSourceConfigValidation:
    """AC-003: Invalid configurations raise clear ValidationError."""

    def test_missing_name_raises_validation_error(self):
        """Missing required field 'name' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate({"type": "rss", "url": "https://example.com"})
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "name" in field_names

    def test_missing_type_raises_validation_error(self):
        """Missing required field 'type' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate({"name": "s", "url": "https://example.com"})
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "type" in field_names

    def test_missing_url_raises_validation_error(self):
        """Missing required field 'url' raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate({"name": "s", "type": "rss"})
        errors = exc_info.value.errors()
        field_names = [e["loc"][-1] for e in errors]
        assert "url" in field_names

    def test_invalid_type_enum_raises_validation_error(self):
        """type value not in ('rss', 'api', 'web') raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate(
                {"name": "s", "type": "ftp", "url": "https://example.com"}
            )
        errors = exc_info.value.errors()
        assert any("type" in str(e["loc"]) for e in errors)

    def test_invalid_url_format_raises_validation_error(self):
        """A malformed URL raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate(
                {"name": "s", "type": "rss", "url": "not-a-valid-url"}
            )
        errors = exc_info.value.errors()
        assert any("url" in str(e["loc"]) for e in errors)

    def test_wrong_type_for_tags_raises_validation_error(self):
        """tags as a non-list type raises ValidationError."""
        with pytest.raises(ValidationError):
            SourceConfig.model_validate(
                {
                    "name": "s",
                    "type": "rss",
                    "url": "https://example.com",
                    "tags": "not-a-list",
                }
            )

    def test_wrong_type_for_schedule_interval_raises_validation_error(self):
        """schedule_interval as a non-integer raises ValidationError."""
        with pytest.raises(ValidationError):
            SourceConfig.model_validate(
                {
                    "name": "s",
                    "type": "rss",
                    "url": "https://example.com",
                    "schedule_interval": "fast",
                }
            )


# ---------------------------------------------------------------------------
# AC-T008-2: Validation collects all errors (not fail-fast)
# ---------------------------------------------------------------------------


class TestCollectAllErrors:
    """AC-T008-2: All validation errors are returned, not just the first."""

    def test_multiple_missing_fields_reported(self):
        """When multiple required fields are missing, all are reported."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate({})
        errors = exc_info.value.errors()
        missing_fields = {e["loc"][-1] for e in errors if e["type"] == "missing"}
        assert "name" in missing_fields
        assert "type" in missing_fields
        assert "url" in missing_fields
        assert len(missing_fields) >= 3

    def test_multiple_type_errors_reported(self):
        """When multiple fields have wrong types, all errors are collected."""
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate(
                {
                    "name": 12345,
                    "type": "invalid_enum",
                    "url": "not-a-url",
                    "tags": "should-be-list",
                    "schedule_interval": "not-int",
                }
            )
        errors = exc_info.value.errors()
        # At least type, url, tags, schedule_interval should each produce an error
        error_fields = {str(e["loc"][-1]) for e in errors}
        assert len(errors) >= 3, (
            f"Expected at least 3 errors for multiple invalid fields, got {len(errors)}: {errors}"
        )
