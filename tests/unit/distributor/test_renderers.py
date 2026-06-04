"""WF-6.1: Renderer abstraction — JinjaRenderer + DigestTemplate async delegation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from intellisource.distributor.templates import get_template
from intellisource.distributor.templates.render import render_jinja
from intellisource.distributor.templates.renderers import JinjaRenderer
from intellisource.distributor.templates.schemas import DigestBundle, DigestItem


def _bundle() -> DigestBundle:
    return DigestBundle(
        title="今日速览",
        top_picks=[DigestItem(title="Item One", summary="sum")],
    )


class TestJinjaRenderer:
    async def test_matches_render_jinja(self) -> None:
        bundle = get_template("daily-brief").aggregate(
            [
                SimpleNamespace(
                    title="Item One",
                    summary="s",
                    tags=["ai"],
                    body_text=None,
                    source_name=None,
                    source_url=None,
                    published_at=None,
                    structured_data=None,
                )
            ],
            {"title": "今日速览"},
        )
        out = await JinjaRenderer().render(
            template_name="daily-brief", fmt="markdown", bundle=bundle, config={}
        )
        assert out == render_jinja("daily-brief", "markdown", bundle)
        assert "今日速览" in out

    async def test_renders_html_with_content(self) -> None:
        bundle = _bundle()
        out = await JinjaRenderer().render(
            template_name="weekly-roundup", fmt="html", bundle=bundle, config={}
        )
        assert "今日速览" in out
        assert "Item One" in out


class _SentinelRenderer:
    """A stub Renderer that ignores the bundle and returns a fixed marker."""

    async def render(self, **kwargs: Any) -> str:
        return "SENTINEL-RENDERER-OUTPUT"


class TestDigestTemplateDelegation:
    async def test_render_delegates_to_injected_renderer(self) -> None:
        """DigestTemplate.render uses the injected renderer for string formats."""
        tmpl = get_template("daily-brief")
        bundle = _bundle()
        out = await tmpl.render(bundle, "markdown", renderer=_SentinelRenderer())
        assert out == "SENTINEL-RENDERER-OUTPUT"

    async def test_render_default_renderer_is_jinja(self) -> None:
        """Without an injected renderer, render falls back to the Jinja code path."""
        tmpl = get_template("daily-brief")
        bundle = _bundle()
        out = await tmpl.render(bundle, "markdown")
        assert out == render_jinja("daily-brief", "markdown", bundle)

    async def test_json_format_bypasses_renderer(self) -> None:
        """The json format returns a dict, never touching the string renderer."""
        tmpl = get_template("json-feed")
        bundle = _bundle()
        out = await tmpl.render(bundle, "json", renderer=_SentinelRenderer())
        assert isinstance(out, dict)
        assert out["title"] == "今日速览"
