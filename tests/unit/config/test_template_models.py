"""P1-b: TemplateConfig structural validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from intellisource.config.template_models import TemplateConfig


def test_valid_config() -> None:
    cfg = TemplateConfig(
        name="t",
        base_template="daily-brief",
        formats=["markdown", "text"],
        default_format="markdown",
        jinja_source={"markdown": "x"},
    )
    assert cfg.name == "t"
    assert cfg.formats == ["markdown", "text"]
    assert cfg.status == "active"


def test_default_format_must_be_in_formats() -> None:
    with pytest.raises(ValidationError):
        TemplateConfig(
            name="t",
            base_template="daily-brief",
            formats=["markdown"],
            default_format="html",
        )


def test_formats_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        TemplateConfig(
            name="t", base_template="daily-brief", formats=[], default_format=""
        )


def test_jinja_source_keys_must_be_subset_of_formats() -> None:
    with pytest.raises(ValidationError):
        TemplateConfig(
            name="t",
            base_template="daily-brief",
            formats=["markdown"],
            default_format="markdown",
            jinja_source={"html": "x"},
        )


def test_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        TemplateConfig(
            name="t",
            base_template="daily-brief",
            formats=["markdown"],
            default_format="markdown",
            status="bogus",
        )


def test_json_only_format_needs_no_source() -> None:
    cfg = TemplateConfig(
        name="t",
        base_template="json-feed",
        formats=["json"],
        default_format="json",
    )
    assert cfg.jinja_source == {}
    assert cfg.default_format == "json"
