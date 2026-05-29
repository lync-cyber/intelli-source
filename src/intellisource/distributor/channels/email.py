"""EmailDistributor — SMTP email distribution channel."""

from __future__ import annotations

import asyncio
import html
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiosmtplib

from intellisource.core.settings import get_settings
from intellisource.distributor.base import BaseDistributor
from intellisource.distributor.channels.constants import MAX_RETRY, RETRY_INTERVAL

if TYPE_CHECKING:
    from intellisource.storage.repositories.push import PushRepository

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
        """Create instance from IS_SMTP_* environment variables.

        Honors IS_SMTP_USE_TLS (default "true"). Accepts "true"/"1"/"yes"
        as truthy; any other value disables implicit TLS so the channel
        can talk to plain SMTP servers like mailhog/mailpit on 1025.
        """
        settings = get_settings()
        host = settings.smtp_host
        user = settings.smtp_user
        password = settings.smtp_password
        if not host or not user or not password:
            raise ValueError(
                "IS_SMTP_HOST, IS_SMTP_USER, and IS_SMTP_PASSWORD are required"
            )
        port_str = settings.smtp_port
        port = int(port_str) if port_str else DEFAULT_SMTP_PORT
        use_tls_str = settings.smtp_use_tls.strip().lower()
        use_tls = use_tls_str in {"true", "1", "yes"}
        return cls(
            smtp_host=host,
            smtp_port=port,
            smtp_user=user,
            smtp_password=password,
            use_tls=use_tls,
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

    async def distribute(
        self,
        content: Any,
        subscription: Any,
    ) -> dict[str, Any]:
        """Distribute content to a subscription via email."""
        content_id = getattr(content, "id", None)
        sub_id = getattr(subscription, "id", None)
        channel = "email"

        to_addr: str = subscription.channel_config.get("to_addr", "")
        subject = getattr(content, "title", "")
        html_body = self.format_html(content)

        async def attempt_fn(
            _attempt: int, is_last: bool
        ) -> tuple[bool, str | None, dict[str, Any]]:
            try:
                await self.send_email(
                    to_addr=to_addr,
                    subject=subject,
                    html_body=html_body,
                )
                return True, None, {}
            except Exception as exc:  # noqa: BLE001
                if not is_last:
                    await asyncio.sleep(RETRY_INTERVAL)
                return False, str(exc), {}

        was_deduped, succeeded, _, error, _ = await self._send_with_dedup_lifecycle(
            sub_id,
            content_id,
            channel,
            attempt_fn=attempt_fn,
            max_retry=MAX_RETRY,
        )

        if was_deduped:
            return self._build_result(
                "deduplicated", channel, str(content_id), str(sub_id)
            )
        if succeeded:
            return self._build_result("sent", channel, str(content_id), str(sub_id))
        return self._build_result(
            "failed", channel, str(content_id), str(sub_id), error=error
        )
