"""P1-b: DbDigestTemplate — DB-backed digest template adapter + string renderer.

A custom template stores its Jinja source per format in the database and names
a built-in ``base_template`` whose aggregation logic it reuses. Rendering goes
through the shared sandboxed Jinja environment (rendering from a *string* rather
than a packaged file), so a user can define a new template at runtime without a
code change or redeploy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from jinja2.exceptions import SecurityError

from intellisource.distributor.templates.db_template import DbDigestTemplate
from intellisource.distributor.templates.render import render_jinja_source
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


def _bundle() -> DigestBundle:
    return DigestBundle(
        title="T",
        sections=[DigestSection(heading="AI", items=[DigestItem(title="hello")])],
    )


# ---------------------------------------------------------------------------
# render_jinja_source — sandboxed string rendering
# ---------------------------------------------------------------------------


def test_render_jinja_source_renders_plain_without_escaping() -> None:
    out = render_jinja_source(
        "{{ bundle.title }}", "markdown", DigestBundle(title="<x>")
    )
    # non-html formats are not HTML-escaped
    assert out == "<x>"


def test_render_jinja_source_autoescapes_html() -> None:
    out = render_jinja_source(
        "<p>{{ bundle.title }}</p>", "html", DigestBundle(title="<x>")
    )
    assert out == "<p>&lt;x&gt;</p>"


def test_render_jinja_source_is_sandboxed() -> None:
    # a classic template-injection escape (walking __class__ to reach Python
    # internals) must be blocked by the sandbox
    with pytest.raises(SecurityError):
        render_jinja_source(
            "{{ bundle.__class__.__mro__ }}", "markdown", DigestBundle(title="x")
        )


# ---------------------------------------------------------------------------
# DbDigestTemplate
# ---------------------------------------------------------------------------


def test_fields_from_constructor() -> None:
    tpl = DbDigestTemplate(
        name="my-tpl",
        formats=["markdown", "text"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={"markdown": "# {{ bundle.title }}"},
    )
    assert tpl.name == "my-tpl"
    assert tpl.formats == frozenset({"markdown", "text"})
    assert tpl.default_format == "markdown"


def test_aggregate_delegates_to_base_builtin_with_merged_config() -> None:
    tpl = DbDigestTemplate(
        name="my",
        formats=["markdown"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={"markdown": "x"},
        aggregate_config={"title": "默认标题"},
    )
    contents = [
        SimpleNamespace(title="A", summary="s", tags=["AI"], structured_data=None)
    ]
    # daily-brief groups by tags into sections; the custom template reuses that
    bundle = tpl.aggregate(contents, {})
    assert bundle.title == "默认标题"
    assert bundle.sections[0].items[0].title == "A"
    # per-call config overrides the stored aggregate_config
    bundle2 = tpl.aggregate(contents, {"title": "覆盖"})
    assert bundle2.title == "覆盖"


@pytest.mark.asyncio
async def test_render_uses_stored_jinja_source() -> None:
    tpl = DbDigestTemplate(
        name="my",
        formats=["markdown"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={"markdown": "# {{ bundle.title }}"},
    )
    out = await tpl.render(_bundle(), "markdown")
    assert out == "# T"


@pytest.mark.asyncio
async def test_render_json_returns_bundle_dict() -> None:
    tpl = DbDigestTemplate(
        name="my",
        formats=["json", "markdown"],
        default_format="markdown",
        base_template="json-feed",
        jinja_source={},
    )
    out = await tpl.render(_bundle(), "json")
    assert isinstance(out, dict)
    assert out["title"] == "T"


@pytest.mark.asyncio
async def test_render_unknown_fmt_falls_back_to_default_format() -> None:
    tpl = DbDigestTemplate(
        name="my",
        formats=["markdown"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={"markdown": "D:{{ bundle.title }}"},
    )
    # html is not a supported format → falls back to default (markdown)
    out = await tpl.render(_bundle(), "html")
    assert out == "D:T"


@pytest.mark.asyncio
async def test_render_missing_source_for_format_falls_back_to_base_file() -> None:
    # format is declared supported but has no stored source → render via the
    # base built-in's packaged .j2 instead of raising
    tpl = DbDigestTemplate(
        name="my",
        formats=["markdown"],
        default_format="markdown",
        base_template="daily-brief",
        jinja_source={},
    )
    out = await tpl.render(_bundle(), "markdown")
    assert isinstance(out, str)
    assert "T" in out
