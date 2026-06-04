"""weekly-roundup — top picks + grouped sections + timeline for a weekly digest."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.builtin._common import timeline_from, to_item
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


class WeeklyRoundupTemplate(DigestTemplate):
    name = "weekly-roundup"
    formats = frozenset({"html"})
    default_format = "html"

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        top_n = int(config.get("top_n", 3))
        items = [to_item(content) for content in contents]
        top_picks = items[:top_n]
        rest = items[top_n:]

        buckets: dict[str, list[DigestItem]] = {}
        order: list[str] = []
        for item in rest:
            key = item.tags[0] if item.tags else "未分类"
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(item)
        sections = [DigestSection(heading=key, items=buckets[key]) for key in order]

        timeline: list[dict[str, str]] = []
        if config.get("include_timeline", True):
            for content in contents:
                timeline.extend(timeline_from(content))

        return DigestBundle(
            title=str(config.get("title", "每周精选")),
            period_label=config.get("period_label"),
            intro=config.get("intro"),
            top_picks=top_picks,
            sections=sections,
            timeline=timeline,
            outro=config.get("outro"),
        )
