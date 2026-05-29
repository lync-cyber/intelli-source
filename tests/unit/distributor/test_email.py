"""Tests for EmailDistributor SMTP email channel.

Covers:
- AC-042: EmailDistributor sends HTML-formatted email via SMTP
- AC-044: Duplicate content is not pushed again
- AC-045: Failed pushes are retried automatically
- AC-T034-1: SMTP config read from env vars (IS_SMTP_HOST/PORT/USER/PASSWORD)
- AC-T034-2: Email body uses HTML template (title/summary/source link)
- AC-T034-3: Supports TLS/SSL encrypted connections
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Lightweight stub data models (no SQLAlchemy dependency)
# ---------------------------------------------------------------------------


@dataclass
class StubContent:
    """Minimal Content for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Test Article"
    summary: str = "A brief summary of the article."
    source_url: str = "https://example.com/article/1"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


@dataclass
class StubSubscription:
    """Minimal Subscription for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "test-sub"
    channel: str = "email"
    channel_config: dict = field(
        default_factory=lambda: {"to_addr": "user@example.com"},
    )


# ---------------------------------------------------------------------------
# Lazy import helper — all tests fail with ModuleNotFoundError until
# the implementation module exists.
# ---------------------------------------------------------------------------


def _import_email_distributor():
    """Import EmailDistributor lazily so tests fail at the right point."""
    from intellisource.distributor.channels.email import EmailDistributor

    return EmailDistributor


# ===================================================================
# AC-042: EmailDistributor sends HTML-formatted email via SMTP
# ===================================================================


class TestEmailDistributorBasic:
    """Basic construction and SMTP sending."""

    def test_instantiation_with_smtp_config(self):
        """EmailDistributor can be created with explicit SMTP parameters."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        assert distributor.smtp_host == "smtp.example.com"
        assert distributor.smtp_port == 587
        assert distributor.smtp_user == "user@example.com"

    def test_inherits_base_distributor(self):
        """EmailDistributor is a subclass of BaseDistributor."""
        cls = _import_email_distributor()
        from intellisource.distributor.base import BaseDistributor

        assert issubclass(cls, BaseDistributor)

    @pytest.mark.asyncio
    async def test_distribute_sends_email(self):
        """distribute() sends an email and returns a PushRecord-style dict."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        distributor.send_email = AsyncMock(
            return_value={"status": "sent"},
        )

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert isinstance(result, dict)
        assert result.get("status") == "sent"
        distributor.send_email.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distribute_returns_push_record_fields(self):
        """Result dict contains subscription_id, content_id, channel."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        distributor.send_email = AsyncMock(
            return_value={
                "status": "sent",
                "subscription_id": str(uuid.uuid4()),
                "content_id": str(uuid.uuid4()),
                "channel": "email",
            },
        )

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert "subscription_id" in result
        assert "content_id" in result
        assert result["channel"] == "email"


# ===================================================================
# AC-T034-1: SMTP config from environment variables
# ===================================================================


class TestEmailDistributorFromEnv:
    """Factory method reads IS_SMTP_* env vars."""

    def test_from_env_reads_env_vars(self, monkeypatch):
        """from_env() creates an instance from IS_SMTP_* env vars."""
        monkeypatch.setenv("IS_SMTP_HOST", "mail.test.com")
        monkeypatch.setenv("IS_SMTP_PORT", "465")
        monkeypatch.setenv("IS_SMTP_USER", "admin@test.com")
        monkeypatch.setenv("IS_SMTP_PASSWORD", "p@ssw0rd")

        cls = _import_email_distributor()
        distributor = cls.from_env()

        assert distributor.smtp_host == "mail.test.com"
        assert distributor.smtp_port == 465
        assert distributor.smtp_user == "admin@test.com"
        assert distributor.smtp_password == "p@ssw0rd"

    def test_from_env_raises_without_required_vars(self, monkeypatch):
        """from_env() raises when required env vars are missing."""
        monkeypatch.delenv("IS_SMTP_HOST", raising=False)
        monkeypatch.delenv("IS_SMTP_PORT", raising=False)
        monkeypatch.delenv("IS_SMTP_USER", raising=False)
        monkeypatch.delenv("IS_SMTP_PASSWORD", raising=False)

        cls = _import_email_distributor()
        with pytest.raises((ValueError, KeyError)):
            cls.from_env()

    def test_from_env_default_port(self, monkeypatch):
        """from_env() uses DEFAULT_SMTP_PORT (587) when IS_SMTP_PORT unset."""
        monkeypatch.setenv("IS_SMTP_HOST", "mail.test.com")
        monkeypatch.delenv("IS_SMTP_PORT", raising=False)
        monkeypatch.setenv("IS_SMTP_USER", "admin@test.com")
        monkeypatch.setenv("IS_SMTP_PASSWORD", "p@ssw0rd")

        cls = _import_email_distributor()
        distributor = cls.from_env()

        assert distributor.smtp_port == 587


# ===================================================================
# AC-T034-2: HTML template formatting (title/summary/source link)
# ===================================================================


class TestEmailHtmlTemplate:
    """format_html() produces HTML with title, summary, and source link."""

    def test_format_html_contains_title(self):
        """HTML output contains the content title."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        content = StubContent(title="Breaking News")
        html = distributor.format_html(content)

        assert "Breaking News" in html

    def test_format_html_contains_summary(self):
        """HTML output contains the content summary."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        content = StubContent(summary="Important summary text")
        html = distributor.format_html(content)

        assert "Important summary text" in html

    def test_format_html_contains_source_link(self):
        """HTML output contains a hyperlink to the source URL."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        content = StubContent(
            source_url="https://example.com/article/42",
        )
        html = distributor.format_html(content)

        assert "https://example.com/article/42" in html
        assert "<a " in html.lower() or "href=" in html.lower()

    def test_format_html_is_valid_html(self):
        """HTML output contains basic HTML structure tags."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        content = StubContent()
        html = distributor.format_html(content)

        html_lower = html.lower()
        assert "<html" in html_lower or "<!doctype" in html_lower


# ===================================================================
# AC-T034-3: TLS/SSL encrypted connections
# ===================================================================


class TestEmailTlsSsl:
    """TLS/SSL configuration support."""

    def test_use_tls_default_true(self):
        """use_tls defaults to True."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        assert distributor.use_tls is True

    def test_use_tls_can_be_disabled(self):
        """use_tls can be set to False."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
            use_tls=False,
        )
        assert distributor.use_tls is False

    @pytest.mark.asyncio
    async def test_send_email_uses_tls_when_enabled(self):
        """send_email() establishes a TLS connection when use_tls=True."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
            use_tls=True,
        )

        with patch(
            "intellisource.distributor.channels.email.aiosmtplib",
            create=True,
        ) as mock_smtp_mod:
            mock_send = AsyncMock(return_value=({}, "OK"))
            mock_smtp_mod.send = mock_send

            await distributor.send_email(
                to_addr="recipient@example.com",
                subject="Test",
                html_body="<html><body>Hello</body></html>",
            )

            # Verify TLS-related argument was passed
            call_kwargs = mock_send.call_args
            assert call_kwargs.kwargs["use_tls"] is True


# ===================================================================
# AC-044: Duplicate content is not pushed again
# ===================================================================


class TestEmailDeduplication:
    """Same content+subscription pair should not be sent twice."""

    @pytest.mark.asyncio
    async def test_duplicate_content_not_resent(self):
        """Second distribute() for same content+sub is deduplicated via push_repo."""
        from unittest.mock import MagicMock

        cls = _import_email_distributor()

        push_repo = MagicMock()
        push_repo.exists = AsyncMock(side_effect=[False, True])
        push_repo.create = AsyncMock(return_value=MagicMock())

        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
            push_repo=push_repo,
        )
        distributor.send_email = AsyncMock(
            return_value={"status": "sent"},
        )

        content = StubContent()
        subscription = StubSubscription()

        # First call should send
        result1 = await distributor.distribute(content, subscription)
        assert result1["status"] in ("sent", "success")

        # Second call with same content+subscription should be deduplicated
        result2 = await distributor.distribute(content, subscription)
        assert result2["status"] in ("skipped", "duplicate", "deduplicated")

        # send_email should only be called once
        assert distributor.send_email.await_count == 1

    @pytest.mark.asyncio
    async def test_different_content_is_sent(self):
        """Different content to same subscription should still be sent."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )
        distributor.send_email = AsyncMock(
            return_value={"status": "sent"},
        )

        content1 = StubContent(title="Article A")
        content2 = StubContent(title="Article B")
        subscription = StubSubscription()

        await distributor.distribute(content1, subscription)
        await distributor.distribute(content2, subscription)

        assert distributor.send_email.await_count == 2


# ===================================================================
# AC-045: Push failure auto-retry
# ===================================================================


class TestEmailRetry:
    """Failed sends should be retried up to MAX_RETRY times."""

    def test_max_retry_constant(self):
        """Module exposes MAX_RETRY = 3."""
        from intellisource.distributor.channels.email import MAX_RETRY

        assert MAX_RETRY == 3

    def test_retry_interval_constant(self):
        """Module exposes RETRY_INTERVAL = 5."""
        from intellisource.distributor.channels.email import RETRY_INTERVAL

        assert RETRY_INTERVAL == 5

    @pytest.mark.asyncio
    async def test_retry_on_smtp_failure(self):
        """distribute() retries on transient SMTP errors."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )

        # Fail twice, succeed on third attempt
        distributor.send_email = AsyncMock(
            side_effect=[
                Exception("Connection refused"),
                Exception("Timeout"),
                {"status": "sent"},
            ],
        )

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert result["status"] == "sent"
        assert distributor.send_email.await_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_returns_failed(self):
        """distribute() returns failed status after MAX_RETRY attempts."""
        cls = _import_email_distributor()
        distributor = cls(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="secret",
        )

        distributor.send_email = AsyncMock(
            side_effect=Exception("Permanent failure"),
        )

        content = StubContent()
        subscription = StubSubscription()
        result = await distributor.distribute(content, subscription)

        assert result["status"] == "failed"
        # Should have tried MAX_RETRY (3) times
        assert distributor.send_email.await_count == 3


# ===================================================================
# AC-042 + constants: DEFAULT_SMTP_PORT
# ===================================================================


class TestEmailConstants:
    """Module-level constants."""

    def test_default_smtp_port(self):
        """Module exposes DEFAULT_SMTP_PORT = 587."""
        from intellisource.distributor.channels.email import (
            DEFAULT_SMTP_PORT,
        )

        assert DEFAULT_SMTP_PORT == 587
