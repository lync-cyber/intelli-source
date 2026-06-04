"""Channel catalog — the single source of truth for available push channels.

Holds display metadata and the env vars each channel needs. The composition root
soft-disables a channel whose ``from_env`` raises; this registry lets the API and
startup diagnostics enumerate channels and report which are configured without
importing the channel implementations (so channel adapters stay independent).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelDescriptor:
    """Static metadata for one distribution channel."""

    name: str
    display_name: str
    required_env: tuple[str, ...]


CHANNEL_DESCRIPTORS: tuple[ChannelDescriptor, ...] = (
    ChannelDescriptor(
        name="email",
        display_name="邮件",
        required_env=("IS_SMTP_HOST", "IS_SMTP_USER", "IS_SMTP_PASSWORD"),
    ),
    ChannelDescriptor(
        name="wechat",
        display_name="微信公众号",
        required_env=("IS_WECHAT_APP_ID", "IS_WECHAT_APP_SECRET"),
    ),
    ChannelDescriptor(
        name="wework",
        display_name="企业微信",
        required_env=(
            "IS_WEWORK_CORP_ID",
            "IS_WEWORK_CORP_SECRET",
            "IS_WEWORK_AGENT_ID",
        ),
    ),
)


def list_channel_descriptors() -> tuple[ChannelDescriptor, ...]:
    """Return all registered channel descriptors."""
    return CHANNEL_DESCRIPTORS


def channel_is_configured(
    descriptor: ChannelDescriptor, env: Mapping[str, str]
) -> bool:
    """True when every required env var for *descriptor* has a non-empty value."""
    return all(env.get(var) for var in descriptor.required_env)
