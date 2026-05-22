"""AC-3: PushRecord recording — three channels each create a PushRecord.

Verifies that PushRepository.create() and BaseDistributor.record_push()
record a PushRecord per channel with the correct status and retry_count.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from intellisource.distributor.base import BaseDistributor
from intellisource.storage.repositories.push import PushRepository

# ---------------------------------------------------------------------------
# Minimal concrete subclass for BaseDistributor (abstract)
# ---------------------------------------------------------------------------


class _FakeDistributor(BaseDistributor):
    async def distribute(self, content: Any, subscription: Any) -> Any:
        return {}


class TestPushRecordThreeChannels:
    """AC-3: record_push for email/wechat/wework each produce a PushRecord."""

    async def test_push_repository_create_records_three_channels(self) -> None:
        """Calling PushRepository.create() for email, wechat, wework each
        produces a PushRecord with status='success' and retry_count=0."""
        subscription_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channels = ["email", "wechat", "wework"]

        # Build a mock session that captures _create_entity calls
        created_records: list[dict[str, Any]] = []

        mock_session = AsyncMock()

        async def _fake_flush() -> None:
            pass

        mock_session.flush = _fake_flush

        # Patch _create_entity to record kwargs and return a mock PushRecord
        async def _fake_create_entity(**kwargs: Any) -> MagicMock:
            created_records.append(kwargs)
            rec = MagicMock()
            rec.id = uuid.uuid4()
            rec.status = kwargs.get("status", "pending")
            rec.retry_count = kwargs.get("retry_count", 0)
            rec.channel = kwargs.get("channel")
            return rec

        repo = PushRepository(session=mock_session)

        with patch.object(repo, "_create_entity", side_effect=_fake_create_entity):
            for ch in channels:
                await repo.create(
                    subscription_id=subscription_id,
                    content_id=content_id,
                    channel=ch,
                    status="success",
                    retry_count=0,
                )

        assert len(created_records) == 3, (
            f"Expected 3 PushRecord creations, got {len(created_records)}"
        )

        recorded_channels = [r["channel"] for r in created_records]
        assert set(recorded_channels) == {"email", "wechat", "wework"}, (
            f"Expected channels {{email, wechat, wework}}, got {set(recorded_channels)}"
        )

        for record in created_records:
            ch = record["channel"]
            assert record["status"] == "success", (
                f"status!=success for ch={ch!r}: {record['status']!r}"
            )
            assert record["retry_count"] == 0, (
                f"retry_count!=0 for ch={ch!r}: {record['retry_count']}"
            )

    async def test_record_push_via_base_distributor_produces_push_record(
        self,
    ) -> None:
        """BaseDistributor.record_push() wired to a mock PushRepository creates
        one record per channel (email/wechat/wework) with status='sent' and
        retry_count=0."""
        subscription_id = uuid.uuid4()
        content_id = uuid.uuid4()
        channels = ["email", "wechat", "wework"]

        mock_repo = AsyncMock(spec=PushRepository)
        created_calls: list[dict[str, Any]] = []

        async def _capture_create(
            subscription_id: uuid.UUID,  # noqa: A002  # positional-or-keyword mirror of repo API
            content_id: uuid.UUID,
            channel: str,
            **kwargs: Any,
        ) -> MagicMock:
            created_calls.append(
                {
                    "subscription_id": subscription_id,
                    "content_id": content_id,
                    "channel": channel,
                    **kwargs,
                }
            )
            rec = MagicMock()
            rec.id = uuid.uuid4()
            return rec

        mock_repo.create = AsyncMock(side_effect=_capture_create)

        distributor = _FakeDistributor()

        for ch in channels:
            await distributor.record_push(
                subscription_id,
                content_id,
                ch,
                status="sent",
                retry_count=0,
                repo=mock_repo,
            )

        assert len(created_calls) == 3, (
            f"Expected 3 calls to PushRepository.create(), got {len(created_calls)}"
        )

        for record in created_calls:
            assert record["status"] == "sent", (
                f"status!=sent for channel={record['channel']!r}: {record['status']!r}"
            )
            assert record["retry_count"] == 0, (
                f"Expected retry_count=0, got {record['retry_count']} "
                f"for channel {record['channel']!r}"
            )

        recorded_channels = [r["channel"] for r in created_calls]
        assert set(recorded_channels) == {"email", "wechat", "wework"}, (
            f"Expected channels {{email, wechat, wework}}, got {set(recorded_channels)}"
        )
