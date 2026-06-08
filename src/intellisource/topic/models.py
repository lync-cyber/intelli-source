"""Pydantic models for the built-in collection topic catalog.

A :class:`Topic` bundles a set of sources with an optional default subscription
template so a single ``enable`` call provisions both the collection targets and
a ready-to-use subscription. Topics are organized along two axes via
``dimension``: ``discipline`` (e.g. 电气工程) and ``industry`` (e.g. 人工智能);
``general`` covers cross-cutting themes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from intellisource.config.models import SourceConfig
from intellisource.config.subscription_models import ChannelType, SubscriptionConfig

Dimension = Literal["discipline", "industry", "general"]


class TopicSource(BaseModel):
    """A collection target inside a topic pack; maps onto :class:`SourceConfig`."""

    name: str
    type: Literal["rss", "api", "web"]
    url: str
    tags: list[str] = Field(default_factory=list)
    discipline_tags: list[str] = Field(default_factory=list)
    schedule_interval: int = 3600
    schedule_adaptive: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.name,
            type=self.type,
            url=self.url,
            tags=self.tags,
            discipline_tags=self.discipline_tags,
            schedule_interval=self.schedule_interval,
            schedule_adaptive=self.schedule_adaptive,
            metadata=self.metadata,
        )


class TopicSubscriptionTemplate(BaseModel):
    """Default subscription generated when a topic is enabled with a channel."""

    name: str | None = None
    match_rules: dict[str, Any] = Field(default_factory=dict)
    frequency: str = "daily"
    discipline_tags: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    """A named collection-target pack along the discipline/industry axis."""

    id: str
    name: str
    dimension: Dimension
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    discipline_tags: list[str] = Field(default_factory=list)
    sources: list[TopicSource] = Field(default_factory=list)
    subscription_template: TopicSubscriptionTemplate | None = None

    def source_configs(self) -> list[SourceConfig]:
        return [s.to_source_config() for s in self.sources]

    def build_subscription(
        self,
        *,
        channel: ChannelType,
        channel_config: dict[str, Any],
        name: str | None = None,
    ) -> SubscriptionConfig:
        """Materialize the topic's subscription template into a SubscriptionConfig."""
        tmpl = self.subscription_template
        sub_name = name or (tmpl.name if tmpl and tmpl.name else f"{self.name} 订阅")
        match_rules = dict(tmpl.match_rules) if tmpl else {}
        # Bind the subscription to this pack's own sources by name. The matcher
        # treats source_names as a strong constraint, so the subscription matches
        # the pack's collected content directly — without depending on tag
        # propagation from source to ProcessedContent (which does not happen).
        # An explicit source_names in the template still wins (setdefault).
        if self.sources:
            match_rules.setdefault("source_names", [s.name for s in self.sources])
        frequency = tmpl.frequency if tmpl else "daily"
        discipline_tags = tmpl.discipline_tags if tmpl else self.discipline_tags
        return SubscriptionConfig(
            name=sub_name,
            channel=channel,
            channel_config=channel_config,
            match_rules=match_rules,
            frequency=frequency,
            discipline_tags=discipline_tags,
        )
