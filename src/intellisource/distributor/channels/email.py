"""EmailDistributor — SMTP email distribution channel."""

from __future__ import annotations

import asyncio
import html
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiosmtplib

from intellisource.distributor.base import BaseDistributor

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository

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
        push_repo: "PushRepository | None" = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.use_tls = use_tls
        self._push_repo = push_repo

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
        title = html.escape(getattr(content, "title", ""))
        summary = html.escape(getattr(content, "summary", ""))
        raw_url = getattr(content, "source_url", "")
        safe_url = quote(raw_url, safe=":/?#[]@!$&'()*+,;=-._~%")
        return (
            "<html><body>"
            f"<h1>{title}</h1>"
            f"<p>{summary}</p>"
            f'<a href="{safe_url}">{html.escape(raw_url)}</a>'
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
        content_id = getattr(content, "id", None)
        sub_id = getattr(subscription, "id", None)
        channel = "email"

        # dedup check
        if self._push_repo is not None:
            is_dup = await self.check_dedup(
                sub_id, content_id, channel, repo=self._push_repo
            )
            if is_dup:
                return self._make_result("deduplicated", str(content_id), str(sub_id))

        to_addr: str = subscription.channel_config.get("to_addr", "")
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
                if self._push_repo is not None:
                    await self.record_push(
                        sub_id,
                        content_id,
                        channel,
                        status="sent",
                        repo=self._push_repo,
                    )
                return self._make_result("sent", str(content_id), str(sub_id))
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await asyncio.sleep(RETRY_INTERVAL)

        error_msg = str(last_err) if last_err else "unknown error"
        if self._push_repo is not None:
            await self.record_push(
                sub_id,
                content_id,
                channel,
                status="failed",
                retry_count=MAX_RETRY,
                error_message=error_msg,
                repo=self._push_repo,
            )
        return self._make_result(
            "failed", str(content_id), str(sub_id), error=error_msg
        )
