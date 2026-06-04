"""Digest template engine: registry, aggregation, and per-format rendering.

Covers the rendering behaviour migrated from the channels' former
``format_html`` / ``format_content`` methods (now owned by templates).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from intellisource.distributor.templates import get_template
from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.registry import (
    TEMPLATE_REGISTRY,
    register_template,
)
from intellisource.distributor.templates.schemas import DigestBundle


def _content(**kwargs: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "title": "",
        "summary": "",
        "body_text": None,
        "tags": [],
        "source_name": None,
        "source_url": None,
        "published_at": None,
        "structured_data": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_builtin_templates_registered(self) -> None:
        for name in (
            "daily-brief",
            "weekly-roundup",
            "topic-deepdive",
            "push-card",
            "json-feed",
        ):
            assert isinstance(get_template(name), DigestTemplate)

    def test_get_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown digest template"):
            get_template("does-not-exist")

    def test_register_template_roundtrip(self) -> None:
        class _Dummy(DigestTemplate):
            name = "dummy-test-template"
            formats = frozenset({"json"})
            default_format = "json"

            def aggregate(
                self, contents: list[Any], config: dict[str, Any]
            ) -> DigestBundle:
                return DigestBundle(title="x")

        try:
            register_template(_Dummy())
            assert get_template("dummy-test-template").name == "dummy-test-template"
        finally:
            TEMPLATE_REGISTRY.pop("dummy-test-template", None)

    def test_digest_template_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            DigestTemplate()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# topic-deepdive (email default) — migrated format_html assertions
# ---------------------------------------------------------------------------


class TestTopicDeepDive:
    def test_html_contains_title_summary_and_source_link(self) -> None:
        tmpl = get_template("topic-deepdive")
        bundle = tmpl.aggregate(
            [
                _content(
                    title="Breaking News",
                    summary="Important summary text",
                    source_url="https://example.com/article/42",
                )
            ],
            {},
        )
        html = tmpl.render(bundle, "html")
        assert "Breaking News" in html
        assert "Important summary text" in html
        assert "https://example.com/article/42" in html
        assert "href=" in html.lower()
        assert "<html" in html.lower()

    def test_html_autoescapes_content(self) -> None:
        tmpl = get_template("topic-deepdive")
        bundle = tmpl.aggregate([_content(title="<script>alert(1)</script>")], {})
        html = tmpl.render(bundle, "html")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_markdown_contains_title(self) -> None:
        tmpl = get_template("topic-deepdive")
        bundle = tmpl.aggregate([_content(title="Deep Title", summary="S")], {})
        md = tmpl.render(bundle, "markdown")
        assert "Deep Title" in md
        assert isinstance(md, str)


# ---------------------------------------------------------------------------
# push-card (wework default) — migrated format_content assertions
# ---------------------------------------------------------------------------


class TestPushCard:
    def test_markdown_contains_title_and_body(self) -> None:
        tmpl = get_template("push-card")
        bundle = tmpl.aggregate(
            [_content(title="Test", summary="Summary", body_text="Body")], {}
        )
        result = tmpl.render(bundle, "markdown")
        assert isinstance(result, str)
        assert "Test" in result
        assert "Body" in result

    def test_text_returns_string(self) -> None:
        tmpl = get_template("push-card")
        bundle = tmpl.aggregate([_content(title="Test", summary="Summary")], {})
        result = tmpl.render(bundle, "text")
        assert isinstance(result, str)
        assert "Test" in result

    def test_news_returns_list_of_articles(self) -> None:
        tmpl = get_template("push-card")
        bundle = tmpl.aggregate(
            [
                _content(
                    title="Test", summary="Summary", source_url="https://example.com/1"
                )
            ],
            {},
        )
        result = tmpl.render(bundle, "news")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["title"] == "Test"
        assert result[0]["url"] == "https://example.com/1"


# ---------------------------------------------------------------------------
# daily-brief — grouping into sections
# ---------------------------------------------------------------------------


class TestDailyBrief:
    def test_aggregate_groups_by_first_tag(self) -> None:
        tmpl = get_template("daily-brief")
        bundle = tmpl.aggregate(
            [
                _content(title="A", tags=["ai"]),
                _content(title="B", tags=["ai"]),
                _content(title="C", tags=["security"]),
                _content(title="D", tags=[]),
            ],
            {},
        )
        headings = {s.heading: [i.title for i in s.items] for s in bundle.sections}
        assert headings["ai"] == ["A", "B"]
        assert headings["security"] == ["C"]
        assert headings["未分类"] == ["D"]

    def test_max_per_section_truncates(self) -> None:
        tmpl = get_template("daily-brief")
        bundle = tmpl.aggregate(
            [_content(title=f"T{i}", tags=["ai"]) for i in range(10)],
            {"max_per_section": 3},
        )
        ai_section = next(s for s in bundle.sections if s.heading == "ai")
        assert len(ai_section.items) == 3

    def test_html_renders_title_and_items(self) -> None:
        tmpl = get_template("daily-brief")
        bundle = tmpl.aggregate(
            [_content(title="Item One", summary="sum", tags=["ai"])],
            {"title": "今日速览"},
        )
        html = tmpl.render(bundle, "html")
        assert "今日速览" in html
        assert "Item One" in html
        assert "ai" in html


# ---------------------------------------------------------------------------
# weekly-roundup + json-feed
# ---------------------------------------------------------------------------


class TestWeeklyRoundupAndJsonFeed:
    def test_weekly_top_picks_and_sections(self) -> None:
        tmpl = get_template("weekly-roundup")
        bundle = tmpl.aggregate(
            [
                _content(title="Top1", tags=["ai"]),
                _content(title="Top2", tags=["ai"]),
                _content(title="Rest1", tags=["web"]),
            ],
            {"top_n": 2},
        )
        assert [i.title for i in bundle.top_picks] == ["Top1", "Top2"]
        html = tmpl.render(bundle, "html")
        assert "Top1" in html
        assert "Rest1" in html

    def test_json_feed_returns_dict_payload(self) -> None:
        tmpl = get_template("json-feed")
        bundle = tmpl.aggregate(
            [_content(title="Machine", summary="readable")],
            {"title": "feed"},
        )
        payload = tmpl.render(bundle, "json")
        assert isinstance(payload, dict)
        assert payload["title"] == "feed"
        assert payload["sections"][0]["items"][0]["title"] == "Machine"

    def test_structured_data_key_points_flow_into_item(self) -> None:
        tmpl = get_template("json-feed")
        bundle = tmpl.aggregate(
            [
                _content(
                    title="X",
                    structured_data={
                        "title": "X",
                        "summary": "s",
                        "timeline": [],
                        "key_points": ["k1", "k2"],
                    },
                )
            ],
            {},
        )
        assert bundle.sections[0].items[0].key_points == ["k1", "k2"]
