"""daily-brief — multi-topic daily digest grouped by tag/source."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.base import DigestTemplate
from intellisource.distributor.templates.builtin._common import to_item
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


class DailyBriefTemplate(DigestTemplate):
    name = "daily-brief"
    formats = frozenset({"html", "markdown", "text"})
    default_format = "html"

    def aggregate(self, contents: list[Any], config: dict[str, Any]) -> DigestBundle:
        group_by = config.get("group_by", "tags")
        max_per = int(config.get("max_per_section", 5))

        buckets: dict[str, list[DigestItem]] = {}
        order: list[str] = []
        for content in contents:
            item = to_item(content)
            if group_by == "source":
                key = item.source_name or "其他来源"
            else:
                key = item.tags[0] if item.tags else "未分类"
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(item)

        sections = [
            DigestSection(heading=key, items=buckets[key][:max_per]) for key in order
        ]
        return DigestBundle(
            title=str(config.get("title", "每日速览")),
            period_label=config.get("period_label"),
            intro=config.get("intro"),
            sections=sections,
        )
