"""WF-5.3: channel send_rendered + DigestDispatcher (assemble→send→record→watermark)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from intellisource.distributor.channels.email import EmailDistributor
from intellisource.distributor.channels.wework import WeWorkDistributor
from intellisource.distributor.digest import DigestPayload
from intellisource.distributor.digest_dispatch import DigestDispatcher, DispatchResult

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
SUB_ID = "11111111-1111-1111-1111-111111111111"
C1 = "22222222-2222-2222-2222-222222222222"
C2 = "33333333-3333-3333-3333-333333333333"


class _FixedClock:
    def now(self) -> datetime:
        return NOW


# --------------------------------------------------------------------------
# channel send_rendered
# --------------------------------------------------------------------------


@dataclass
class _Sub:
    id: str = SUB_ID
    channel: str = "email"
    channel_config: dict[str, Any] = field(default_factory=dict)


class TestEmailSendRendered:
    async def test_sends_html_body_as_email(self) -> None:
        dist = EmailDistributor(smtp_host="h", smtp_user="u@x.io", smtp_password="p")
        calls: list[dict[str, Any]] = []

        async def _fake_send(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"status": "sent"}

        dist.send_email = _fake_send  # type: ignore[method-assign]
        sub = _Sub(channel="email", channel_config={"to_addr": "rcpt@x.io"})

        result = await dist.send_rendered(
            sub, title="每日速览", body="<p>hello</p>", fmt="html"
        )

        assert result["status"] == "sent"
        assert calls == [
            {"to_addr": "rcpt@x.io", "subject": "每日速览", "html_body": "<p>hello</p>"}
        ]

    async def test_failure_returns_failed_status(self) -> None:
        dist = EmailDistributor(smtp_host="h", smtp_user="u@x.io", smtp_password="p")

        async def _boom(**_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("smtp down")

        dist.send_email = _boom  # type: ignore[method-assign]
        sub = _Sub(channel_config={"to_addr": "rcpt@x.io"})

        result = await dist.send_rendered(sub, title="t", body="b", fmt="html")
        assert result["status"] == "failed"
        assert "smtp down" in result["error"]


class TestWeWorkSendRendered:
    def _dist(self) -> WeWorkDistributor:
        return WeWorkDistributor(
            redis=object(),
            http_client=object(),
            corp_id="c",
            corp_secret="s",
            agent_id=1,
        )

    async def test_markdown_body_uses_markdown_sender(self) -> None:
        dist = self._dist()
        calls: list[tuple[str, str]] = []

        async def _md(user_id: str, body: str) -> dict[str, Any]:
            calls.append((user_id, body))
            return {"errcode": 0}

        dist.send_markdown_message = _md  # type: ignore[method-assign]
        sub = _Sub(channel="wework", channel_config={"user_id": "u1"})

        result = await dist.send_rendered(sub, title="t", body="# 标题", fmt="markdown")
        assert result["status"] == "sent"
        assert calls == [("u1", "# 标题")]

    async def test_text_fmt_uses_text_sender(self) -> None:
        dist = self._dist()
        calls: list[tuple[str, str]] = []

        async def _text(user_id: str, body: str) -> dict[str, Any]:
            calls.append((user_id, body))
            return {"errcode": 0}

        dist.send_text_message = _text  # type: ignore[method-assign]
        sub = _Sub(channel="wework", channel_config={"user_id": "u2"})

        result = await dist.send_rendered(sub, title="t", body="纯文本", fmt="text")
        assert result["status"] == "sent"
        assert calls == [("u2", "纯文本")]

    async def test_api_errcode_returns_failed(self) -> None:
        dist = self._dist()

        async def _md(user_id: str, body: str) -> dict[str, Any]:
            return {"errcode": 40001, "errmsg": "invalid token"}

        dist.send_markdown_message = _md  # type: ignore[method-assign]
        sub = _Sub(channel="wework", channel_config={"user_id": "u1"})

        result = await dist.send_rendered(sub, title="t", body="b", fmt="markdown")
        assert result["status"] == "failed"
        assert "invalid token" in result["error"]


# --------------------------------------------------------------------------
# DigestDispatcher
# --------------------------------------------------------------------------


class _StubAssembler:
    def __init__(self, payload: DigestPayload | None) -> None:
        self._payload = payload
        self.calls: list[Any] = []

    async def assemble(
        self, subscription: Any, contents: list[Any]
    ) -> DigestPayload | None:
        self.calls.append((subscription, contents))
        return self._payload


class _StubChannel:
    def __init__(self, *, status: str = "sent", raises: bool = False) -> None:
        self._status = status
        self._raises = raises
        self.sent: list[dict[str, Any]] = []

    async def send_rendered(
        self, subscription: Any, *, title: str, body: str, fmt: str
    ) -> dict[str, Any]:
        if self._raises:
            raise NotImplementedError("channel cannot render digests")
        self.sent.append({"title": title, "body": body, "fmt": fmt})
        if self._status == "sent":
            return {"status": "sent"}
        return {"status": "failed", "error": "boom"}


class _StubPushRepo:
    def __init__(self, *, existing: set[str] | None = None) -> None:
        self._existing = existing or set()
        self.created: list[dict[str, Any]] = []

    async def exists(self, subscription_id: Any, content_id: Any, channel: str) -> bool:
        return str(content_id) in self._existing

    async def create(self, **kwargs: Any) -> None:
        self.created.append(kwargs)


class _StubSubRepo:
    def __init__(self) -> None:
        self.updates: list[tuple[Any, dict[str, Any]]] = []

    async def update(self, id: Any, **kwargs: Any) -> None:  # noqa: A002
        self.updates.append((id, kwargs))


def _payload(
    channel: str = "email", content_ids: list[str] | None = None
) -> DigestPayload:
    return DigestPayload(
        subscription=_Sub(id=SUB_ID, channel=channel),
        channel=channel,
        title="每日速览",
        body="<p>x</p>",
        fmt="html",
        content_ids=content_ids if content_ids is not None else [C1, C2],
    )


def _dispatcher(assembler: _StubAssembler, channel: _StubChannel) -> DigestDispatcher:
    return DigestDispatcher(
        assembler=assembler,  # type: ignore[arg-type]
        channels={"email": channel},  # type: ignore[dict-item]
        clock=_FixedClock(),
    )


class TestDispatch:
    async def test_sends_records_and_sets_watermark(self) -> None:
        channel = _StubChannel()
        disp = _dispatcher(_StubAssembler(_payload()), channel)
        push, subs = _StubPushRepo(), _StubSubRepo()

        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )

        assert isinstance(result, DispatchResult)
        assert result.status == "sent"
        assert result.content_count == 2
        # one rendered message sent (not one per content)
        assert len(channel.sent) == 1
        assert channel.sent[0]["body"] == "<p>x</p>"
        # one PushRecord per content
        assert {str(c["content_id"]) for c in push.created} == {C1, C2}
        # watermark advanced to clock-now
        assert subs.updates == [(uuid.UUID(SUB_ID), {"last_sent_at": NOW})]

    async def test_skips_when_assembler_returns_none(self) -> None:
        channel = _StubChannel()
        disp = _dispatcher(_StubAssembler(None), channel)
        push, subs = _StubPushRepo(), _StubSubRepo()

        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )
        assert result.status == "skipped"
        assert channel.sent == []
        assert push.created == []
        assert subs.updates == []

    async def test_already_pushed_content_not_recorded_again(self) -> None:
        channel = _StubChannel()
        disp = _dispatcher(_StubAssembler(_payload()), channel)
        push, subs = _StubPushRepo(existing={C1}), _StubSubRepo()

        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )
        assert result.status == "sent"
        assert result.content_count == 1
        assert {str(c["content_id"]) for c in push.created} == {C2}

    async def test_failed_send_skips_record_and_watermark(self) -> None:
        channel = _StubChannel(status="failed")
        disp = _dispatcher(_StubAssembler(_payload()), channel)
        push, subs = _StubPushRepo(), _StubSubRepo()

        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )
        assert result.status == "failed"
        assert push.created == []
        assert subs.updates == []

    async def test_unsupported_channel_marks_skipped(self) -> None:
        channel = _StubChannel(raises=True)
        disp = _dispatcher(_StubAssembler(_payload()), channel)
        push, subs = _StubPushRepo(), _StubSubRepo()

        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )
        assert result.status == "skipped"
        assert result.reason == "channel_unsupported"
        assert push.created == []

    async def test_push_records_carry_render_mode(self) -> None:
        """_record stamps each PushRecord with the payload's render_mode."""
        channel = _StubChannel()
        payload = _payload()
        payload.render_mode = "llm-freeform"
        disp = _dispatcher(_StubAssembler(payload), channel)
        push, subs = _StubPushRepo(), _StubSubRepo()

        await disp.dispatch(_Sub(), [object()], push_repo=push, subscription_repo=subs)

        assert len(push.created) == 2
        assert all(c.get("render_mode") == "llm-freeform" for c in push.created)

    async def test_channel_not_configured_marks_skipped(self) -> None:
        disp = DigestDispatcher(
            assembler=_StubAssembler(_payload(channel="wechat")),  # type: ignore[arg-type]
            channels={},
            clock=_FixedClock(),
        )
        push, subs = _StubPushRepo(), _StubSubRepo()
        result = await disp.dispatch(
            _Sub(), [object()], push_repo=push, subscription_repo=subs
        )
        assert result.status == "skipped"
        assert result.reason == "channel_not_configured"
