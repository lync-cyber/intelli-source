"""EmailDistributor — SMTP email distribution channel."""

from __future__ import annotations

import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

try:
    import aiosmtplib
except ImportError:  # pragma: no cover
    aiosmtplib = None

from intellisource.distributor.base import BaseDistributor

MAX_RETRY: int = 3
RETRY_INTERVAL: int = 5
DEFAULT_SMTP_PORT: int = 587


class EmailDistributor(BaseDistributor):
    """Distribute content via SMTP email."""

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int = DEFAULT_SMTP_PORT,
        smtp_user: str,
        smtp_password: str,
        use_tls: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self._sent_keys: set[str] = set()

    @classmethod
    def from_env(cls) -> EmailDistributor:
        """Create instance from IS_SMTP_* environment variables."""
        host = os.environ.get("IS_SMTP_HOST")
        user = os.environ.get("IS_SMTP_USER")
        password = os.environ.get("IS_SMTP_PASSWORD")
        if not host or not user or not password:
            raise ValueError(
                "IS_SMTP_HOST, IS_SMTP_USER, and IS_SMTP_PASSWORD are required"
            )
        port_str = os.environ.get("IS_SMTP_PORT")
        port = int(port_str) if port_str else DEFAULT_SMTP_PORT
        return cls(
            smtp_host=host,
            smtp_port=port,
            smtp_user=user,
            smtp_password=password,
        )

    def format_html(self, content: Any) -> str:
        """Render content as an HTML email body."""
        title = getattr(content, "title", "")
        summary = getattr(content, "summary", "")
        source_url = getattr(content, "source_url", "")
        return (
            "<html><body>"
            f"<h1>{title}</h1>"
            f"<p>{summary}</p>"
            f'<a href="{source_url}">{source_url}</a>'
            "</body></html>"
        )

    async def send_email(
        self,
        *,
        to_addr: str,
        subject: str,
        html_body: str,
    ) -> dict[str, Any]:
        """Send an email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = to_addr
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=self.smtp_host,
            port=self.smtp_port,
            username=self.smtp_user,
            password=self.smtp_password,
            use_tls=self.use_tls,
        )
        return {"status": "sent"}

    def _make_result(
        self,
        status: str,
        content_id: str,
        sub_id: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build a standard push-result dict."""
        return {
            "status": status,
            "subscription_id": sub_id,
            "content_id": content_id,
            "channel": "email",
            **extra,
        }

    async def distribute(
        self,
        content: Any,
        subscription: Any,
    ) -> dict[str, Any]:
        """Distribute content to a subscription via email."""
        content_id = str(getattr(content, "id", ""))
        sub_id = str(getattr(subscription, "id", ""))
        dedup_key = f"{content_id}:{sub_id}"

        if dedup_key in self._sent_keys:
            return self._make_result(
                "deduplicated",
                content_id,
                sub_id,
            )

        to_addr: str = subscription.channel_config.get(
            "to_addr",
            "",
        )
        subject = getattr(content, "title", "")
        html_body = self.format_html(content)

        last_err: Exception | None = None
        for _ in range(MAX_RETRY):
            try:
                await self.send_email(
                    to_addr=to_addr,
                    subject=subject,
                    html_body=html_body,
                )
                self._sent_keys.add(dedup_key)
                return self._make_result(
                    "sent",
                    content_id,
                    sub_id,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc

        return self._make_result(
            "failed",
            content_id,
            sub_id,
            error=str(last_err),
        )
