"""SubscriptionConfig Pydantic model for subscription configuration validation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChannelType = Literal["wechat", "wework", "email"]


class SubscriptionConfig(BaseModel):
    """Configuration for a single subscription, mirrored from Subscription ORM."""

    name: str
    channel: ChannelType
    channel_config: dict[str, Any] = Field(default_factory=dict)
    match_rules: dict[str, Any] = Field(default_factory=dict)
    frequency: str = "realtime"
    quiet_hours: dict[str, Any] | None = None
    timezone: str = "Asia/Shanghai"
    discipline_tags: list[str] = Field(default_factory=list)
