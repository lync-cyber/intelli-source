"""Unit tests for distributor.templates.discovery pure functions (B-075)."""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# list_file_overrides
# ---------------------------------------------------------------------------


def test_list_file_overrides_returns_empty_for_empty_dir(tmp_path: Path) -> None:
    """Returns empty dict when directory has no .j2 files."""
    from intellisource.distributor.templates.discovery import list_file_overrides

    result = list_file_overrides(user_dir=tmp_path)
    assert result == {}


def test_list_file_overrides_parses_single_file(tmp_path: Path) -> None:
    """A single daily-brief.markdown.j2 → {daily-brief: [markdown]}."""
    from intellisource.distributor.templates.discovery import list_file_overrides

    (tmp_path / "daily-brief.markdown.j2").write_text("# {{ bundle.title }}")
    result = list_file_overrides(user_dir=tmp_path)
    assert "daily-brief" in result
    assert result["daily-brief"] == ["markdown"]


def test_list_file_overrides_aggregates_multiple_formats(tmp_path: Path) -> None:
    """Multiple formats for same template are aggregated and sorted."""
    from intellisource.distributor.templates.discovery import list_file_overrides

    (tmp_path / "daily-brief.markdown.j2").write_text("a")
    (tmp_path / "daily-brief.html.j2").write_text("b")
    (tmp_path / "daily-brief.text.j2").write_text("c")
    result = list_file_overrides(user_dir=tmp_path)
    assert "daily-brief" in result
    assert sorted(result["daily-brief"]) == result["daily-brief"]
    assert set(result["daily-brief"]) == {"html", "markdown", "text"}


def test_list_file_overrides_ignores_non_j2_files(tmp_path: Path) -> None:
    """Non-.j2 files are ignored."""
    from intellisource.distributor.templates.discovery import list_file_overrides

    (tmp_path / "daily-brief.markdown.txt").write_text("a")
    (tmp_path / "README.md").write_text("b")
    result = list_file_overrides(user_dir=tmp_path)
    assert result == {}


def test_list_file_overrides_handles_missing_directory() -> None:
    """Non-existent directory returns empty dict (no crash)."""
    from intellisource.distributor.templates.discovery import list_file_overrides

    result = list_file_overrides(user_dir=Path("/nonexistent/path/xyz"))
    assert result == {}


# ---------------------------------------------------------------------------
# sample_bundle
# ---------------------------------------------------------------------------


def test_sample_bundle_returns_digest_bundle_with_title() -> None:
    """sample_bundle returns a DigestBundle with a non-empty title."""
    from intellisource.distributor.templates.discovery import sample_bundle
    from intellisource.distributor.templates.schemas import DigestBundle

    result = sample_bundle()
    assert isinstance(result, DigestBundle)
    assert len(result.title) > 0


def test_sample_bundle_has_at_least_one_top_pick() -> None:
    """sample_bundle includes at least one top_picks item."""
    from intellisource.distributor.templates.discovery import sample_bundle

    result = sample_bundle()
    assert len(result.top_picks) >= 1


def test_sample_bundle_has_at_least_one_section() -> None:
    """sample_bundle includes at least one section."""
    from intellisource.distributor.templates.discovery import sample_bundle

    result = sample_bundle()
    assert len(result.sections) >= 1


def test_sample_bundle_has_at_least_one_timeline_entry() -> None:
    """sample_bundle includes at least one timeline entry."""
    from intellisource.distributor.templates.discovery import sample_bundle

    result = sample_bundle()
    assert len(result.timeline) >= 1


# ---------------------------------------------------------------------------
# validate_overrides
# ---------------------------------------------------------------------------


def test_validate_overrides_passes_valid_jinja(tmp_path: Path) -> None:
    """A valid Jinja template referencing bundle produces no error issues."""
    from intellisource.distributor.templates.discovery import validate_overrides

    tmpl_src = (
        "# {{ bundle.title }}\n"
        "{% for s in bundle.sections %}{{ s.heading }}{% endfor %}"
    )
    (tmp_path / "daily-brief.markdown.j2").write_text(tmpl_src)
    issues = validate_overrides(user_dir=tmp_path)
    errors = [i for i in issues if i.severity == "error"]
    assert errors == []


def test_validate_overrides_only_filters_to_named_template(tmp_path: Path) -> None:
    """only=<name> validates just that template, ignoring other broken files."""
    from intellisource.distributor.templates.discovery import validate_overrides

    (tmp_path / "daily-brief.markdown.j2").write_text("# {{ bundle.title }}")
    (tmp_path / "push-card.text.j2").write_text("{% if %}broken")
    scoped = validate_overrides(user_dir=tmp_path, only="daily-brief")
    assert all(i.template == "daily-brief" for i in scoped)
    assert not any(i.template == "push-card" for i in scoped)
    all_issues = validate_overrides(user_dir=tmp_path)
    assert any(i.template == "push-card" and i.severity == "error" for i in all_issues)


def test_validate_overrides_detects_syntax_error(tmp_path: Path) -> None:
    """A file with a Jinja syntax error produces an error-severity issue."""
    from intellisource.distributor.templates.discovery import validate_overrides

    (tmp_path / "daily-brief.markdown.j2").write_text(
        "{% if bundle.title %} not closed"
    )
    issues = validate_overrides(user_dir=tmp_path)
    errors = [i for i in issues if i.severity == "error"]
    assert len(errors) >= 1
    # message should contain file context
    assert any("daily-brief" in e.template for e in errors)


def test_validate_overrides_warns_on_unknown_template_name(tmp_path: Path) -> None:
    """A file whose stem does not match any built-in name gets a warning."""
    from intellisource.distributor.templates.discovery import validate_overrides

    (tmp_path / "daily_brief.markdown.j2").write_text("# {{ bundle.title }}")
    issues = validate_overrides(user_dir=tmp_path)
    warnings = [i for i in issues if i.severity == "warning"]
    assert len(warnings) >= 1
    assert any("daily_brief" in w.template for w in warnings)


def test_validate_overrides_warning_message_mentions_kebab(tmp_path: Path) -> None:
    """Warning message mentions kebab/snake mis-match or silent-ignore."""
    from intellisource.distributor.templates.discovery import validate_overrides

    (tmp_path / "daily_brief.text.j2").write_text("{{ bundle.title }}")
    issues = validate_overrides(user_dir=tmp_path)
    warnings = [i for i in issues if i.severity == "warning"]
    assert len(warnings) >= 1
    w = warnings[0]
    assert (
        "kebab" in w.message.lower()
        or "snake" in w.message.lower()
        or "静默" in w.message
        or "疑似" in w.message
    )


def test_validate_overrides_no_warning_for_known_builtin_name(tmp_path: Path) -> None:
    """A file matching a built-in name does not emit a warning."""
    from intellisource.distributor.templates.discovery import validate_overrides

    (tmp_path / "daily-brief.markdown.j2").write_text("# {{ bundle.title }}")
    issues = validate_overrides(user_dir=tmp_path)
    warnings = [i for i in issues if i.severity == "warning"]
    assert warnings == []


# ---------------------------------------------------------------------------
# render_preview
# ---------------------------------------------------------------------------


def test_render_preview_known_template_returns_non_empty_string() -> None:
    """render_preview daily-brief/markdown returns non-empty rendered string."""
    from intellisource.distributor.templates.discovery import render_preview

    result = render_preview("daily-brief", "markdown")
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_preview_contains_sample_title() -> None:
    """render_preview output contains the sample bundle title substring."""
    from intellisource.distributor.templates.discovery import (
        render_preview,
        sample_bundle,
    )

    bundle = sample_bundle()
    result = render_preview("daily-brief", "markdown")
    # The rendered output should contain words from the sample title
    assert bundle.title in result or any(
        word in result for word in bundle.title.split() if len(word) > 2
    )


def test_render_preview_unknown_template_raises_value_error() -> None:
    """render_preview with unknown name raises ValueError."""
    from intellisource.distributor.templates.discovery import render_preview

    with pytest.raises(ValueError, match="Unknown"):
        render_preview("no-such-template", "markdown")


def test_render_preview_none_fmt_falls_back_to_default() -> None:
    """render_preview with fmt=None uses the template's default format."""
    from intellisource.distributor.templates.discovery import render_preview

    # Should not raise; daily-brief default is html
    result = render_preview("daily-brief", None)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_preview_unsupported_fmt_falls_back_to_default() -> None:
    """render_preview with unsupported fmt falls back to default_format."""
    from intellisource.distributor.templates.discovery import render_preview

    # weekly-roundup only supports html; passing an unsupported fmt should not raise
    result = render_preview("weekly-roundup", "nonexistent-format")
    assert isinstance(result, str)
    assert len(result) > 0
