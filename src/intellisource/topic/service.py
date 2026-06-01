"""TopicService — enable a built-in topic pack (sources + default subscription).

Enabling a topic is the single business entrypoint shared by the API and CLI:
it additively syncs the pack's sources (recording a version snapshot, so the
change is rollback-able) and, when a channel is supplied, creates the topic's
default subscription. Both writes route through the existing source/subscription
services so behaviour stays identical to manual provisioning.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.config.subscription_models import ChannelType
from intellisource.source.service import SourceConfigService
from intellisource.subscription.service import SubscriptionService
from intellisource.topic.loader import TopicLoader
from intellisource.topic.models import Topic


class TopicNotFoundError(LookupError):
    """Raised when an unknown topic id is requested."""


class TopicService:
    """Catalog reads + topic enablement over source/subscription services."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        loader: TopicLoader | None = None,
        source_service: SourceConfigService | None = None,
        subscription_service: SubscriptionService | None = None,
    ) -> None:
        self._session = session
        self._loader = loader if loader is not None else TopicLoader()
        self._source_service = (
            source_service
            if source_service is not None
            else SourceConfigService(session)
        )
        self._subscription_service = (
            subscription_service
            if subscription_service is not None
            else SubscriptionService(session)
        )

    def list_topics(self) -> list[Topic]:
        return self._loader.load_all()

    def get_topic(self, topic_id: str) -> Topic | None:
        return self._loader.load_by_id(topic_id)

    async def enable(
        self,
        topic_id: str,
        *,
        channel: ChannelType | None = None,
        channel_config: dict[str, Any] | None = None,
        create_subscription: bool = True,
        subscription_name: str | None = None,
    ) -> dict[str, Any]:
        """Provision a topic pack. Raises TopicNotFoundError on unknown id.

        Validation errors from the source/subscription validators propagate to
        the caller (the API maps them to 400).
        """
        topic = self.get_topic(topic_id)
        if topic is None:
            raise TopicNotFoundError(topic_id)

        sync_result = await self._source_service.bulk_sync_with_version(
            topic.source_configs(), author=f"topic:{topic_id}"
        )

        subscription: dict[str, Any] | None = None
        if create_subscription and channel is not None:
            sub_cfg = topic.build_subscription(
                channel=channel,
                channel_config=channel_config or {},
                name=subscription_name,
            )
            sub = await self._subscription_service.create(sub_cfg)
            subscription = {
                "id": str(sub.id),
                "name": sub.name,
                "channel": sub.channel,
            }

        return {
            "topic_id": topic.id,
            "topic_name": topic.name,
            "dimension": topic.dimension,
            "sources_loaded": sync_result.get("loaded_count", 0),
            "source_version": sync_result.get("version"),
            "source_errors": sync_result.get("errors", []),
            "subscription": subscription,
        }
