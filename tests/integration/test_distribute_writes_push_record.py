"""Integration test for AC-7 — T-097 RED phase.

AC-7: `_distribute_execute` must drive the real DistributorFacade so that at
least one PushRecord row is written and the persisted recipient information
is PII-masked (no plaintext email `@` or 11-digit phone numbers).

These tests are expected to FAIL in RED phase because:
- `build_distributor_facade()` still returns the T-095 stub `DistributorFacade`
  whose `distribute()` returns `{"status": "pending", "reason": "stub", ...}`.
- The stub never calls `PushRepository.create`, so no PushRecord rows land in
  the DB and the PII-mask assertion is meaningless.
- After T-097 GREEN, `build_distributor_facade` builds the real facade with
  injected channels + matcher; `_distribute_execute` exercises the full
  pipeline and persists masked PushRecord rows.
"""

from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tools import _distribute_execute
from intellisource.composition import build_distributor_facade

# ---------------------------------------------------------------------------
# PII detection helpers
# ---------------------------------------------------------------------------

_EMAIL_PLAINTEXT_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PLAINTEXT_RE = re.compile(r"\b\d{11}\b")


def _contains_plaintext_pii(value: object) -> bool:
    """Return True if value (or nested strings inside dict/list) contain raw
    PII strings such as `foo@bar.com` or 11-digit phone numbers."""
    if isinstance(value, str):
        if _EMAIL_PLAINTEXT_RE.search(value):
            return True
        if _PHONE_PLAINTEXT_RE.search(value):
            return True
        return False
    if isinstance(value, dict):
        return any(_contains_plaintext_pii(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_plaintext_pii(v) for v in value)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session_factory(
    content_id: str | None = None,
    subscription_id: str | None = None,
) -> Any:
    """Return an async context manager session_factory backed by AsyncMock.

    Yields a session that returns a mock ProcessedContent and one mock
    Subscription so the DistributorFacade 5-step pipeline reaches record_push.
    """
    cid = uuid.UUID(content_id) if content_id else uuid.uuid4()
    sid = uuid.UUID(subscription_id) if subscription_id else uuid.uuid4()

    mock_content = MagicMock()
    mock_content.id = cid
    mock_content.title = "test article"
    mock_content.body_text = "test body"
    mock_content.tags = []

    mock_sub = MagicMock()
    mock_sub.id = sid
    mock_sub.status = "active"
    mock_sub.channel = "email"
    mock_sub.channel_config = {"to_addr": "user@example.com"}
    mock_sub.match_rules = {"keywords": ["test"]}
    mock_sub.frequency = "realtime"
    mock_sub.quiet_hours = None

    mock_scalars_result = MagicMock()
    mock_scalars_result.all = MagicMock(return_value=[mock_sub])

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_content)
    mock_session.scalars = AsyncMock(return_value=mock_scalars_result)

    @asynccontextmanager
    async def _session_factory() -> AsyncIterator[Any]:
        yield mock_session

    return _session_factory


def _make_tool_deps_with_real_facade(
    content_id: str | None = None,
    subscription_id: str | None = None,
) -> ToolDeps:
    """ToolDeps backed by the production build_distributor_facade.

    Uses an AsyncMock session_factory so the real DistributorFacade
    pipeline can load content + subscriptions and reach record_push.
    The email channel is replaced with an AsyncMock that returns
    {"status": "sent"} so no real SMTP connection is attempted.
    """
    session_factory = _make_mock_session_factory(content_id, subscription_id)
    redis_client = MagicMock(name="redis_client")
    facade = build_distributor_facade(session_factory, redis_client)

    # Replace real SMTP/WeChat/WeWork channels with mocks so channel.distribute
    # succeeds without network I/O, allowing the pipeline to reach record_push.
    mock_email_channel = AsyncMock()
    mock_email_channel.distribute = AsyncMock(return_value={"status": "sent"})
    facade._channels["email"] = mock_email_channel

    return ToolDeps(
        session_factory=session_factory,
        llm_gateway=None,
        pipeline_engine=None,
        search_engine=None,
        collector_registry=None,
        distributor=facade,
    )


# ---------------------------------------------------------------------------
# AC-7: distribute writes PushRecord with PII-masked recipient
# ---------------------------------------------------------------------------


class TestDistributeWritesPushRecord:
    """AC-7: `_distribute_execute` must trigger PushRepository.create and the
    persisted row must not carry plaintext recipient PII."""

    async def test_distribute_returns_real_facade_result_shape(self) -> None:
        """After T-097 the facade returns ok + matched/sent/skipped counters.

        RED failure: T-095 stub returns `{"status": "pending", "reason": ...}`
        without the counters the real facade is contracted to produce.
        """
        tool_deps = _make_tool_deps_with_real_facade()
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        envelope = await _distribute_execute(
            content_id=content_id,
            subscription_id=subscription_id,
            tool_deps=tool_deps,
        )

        # Outer envelope: {"status": "ok", "tool": "distribute", "result": ...}
        inner = envelope.get("result", {})
        assert isinstance(inner, dict), (
            f"_distribute_execute must return a dict result, got {type(inner)}"
        )
        assert inner.get("status") == "ok", (
            f"facade result.status must be 'ok', got {inner.get('status')!r}."
            f"Stub still in place: result={inner!r}"
        )
        assert "matched" in inner, (
            f"facade must report 'matched' counter; keys={list(inner.keys())!r}"
        )
        assert "sent" in inner, (
            f"facade must report 'sent' counter; keys={list(inner.keys())!r}"
        )
        assert "skipped" in inner, (
            f"facade must report 'skipped' counter; keys={list(inner.keys())!r}"
        )

    async def test_distribute_persists_at_least_one_push_record(self) -> None:
        """T-097 facade must call PushRepository.create at least once.

        RED failure: the T-095 stub returns immediately without touching
        PushRepository, so the spy captures zero calls.
        """
        from intellisource.storage.repositories.push import PushRepository

        tool_deps = _make_tool_deps_with_real_facade()
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        captured: list[dict[str, Any]] = []

        async def _spy_create(self_: object, **kwargs: Any) -> MagicMock:
            captured.append(kwargs)
            rec = MagicMock()
            rec.id = uuid.uuid4()
            return rec

        with patch.object(PushRepository, "create", new=_spy_create):
            await _distribute_execute(
                content_id=content_id,
                subscription_id=subscription_id,
                tool_deps=tool_deps,
            )

        assert len(captured) >= 1, (
            f"facade must call PushRepository.create at least once; "
            f"got {len(captured)} calls. T-097 distribute pipeline is not wired."
        )

    async def test_distribute_pushrecord_kwargs_have_no_plaintext_pii(self) -> None:
        """All kwargs passed to PushRepository.create must be PII-masked.

        RED failure: the T-095 stub never reaches PushRepository.create, so
        the per-kwarg scan trivially passes — but the empty-captures
        assertion above already establishes the RED signal. This test
        becomes meaningful (and must continue to pass) after T-097 lands.
        """
        from intellisource.storage.repositories.push import PushRepository

        # Subscription channel_config carries plaintext PII that the facade
        # must mask before persistence.
        tool_deps = _make_tool_deps_with_real_facade()
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        # Inject sentinel plaintext PII via kwargs the facade is free to
        # propagate; the real facade must mask before passing to repo.create.
        extra_kwargs = {
            "_recipient_hint_email": "user-secret@example.com",
            "_recipient_hint_phone": "13812345678",
        }

        captured: list[dict[str, Any]] = []

        async def _spy_create(self_: object, **kwargs: Any) -> MagicMock:
            captured.append(kwargs)
            rec = MagicMock()
            rec.id = uuid.uuid4()
            return rec

        with patch.object(PushRepository, "create", new=_spy_create):
            await _distribute_execute(
                content_id=content_id,
                subscription_id=subscription_id,
                tool_deps=tool_deps,
                **extra_kwargs,
            )

        # AC-7 contract: zero captured calls means PushRecord never persisted (RED)
        assert len(captured) >= 1, (
            "PushRepository.create must be called by the real facade; "
            f"got {len(captured)} calls — T-097 facade not wired."
        )
        for idx, kw in enumerate(captured):
            assert not _contains_plaintext_pii(kw), (
                f"PushRepository.create call #{idx} contains plaintext PII: {kw!r}. "
                "T-097 facade must mask recipient PII before persistence."
            )

    async def test_distribute_envelope_carries_no_plaintext_pii(self) -> None:
        """The dict returned by `_distribute_execute` must not leak plaintext PII.

        RED failure: the stub embeds the raw `content_id` / `subscription_id`
        in the response (not PII per se), but more importantly the stub does
        not mask any future recipient info. After T-097, with PII-tagged
        inputs flowing through the facade, the return envelope must be clean.
        """
        tool_deps = _make_tool_deps_with_real_facade()

        envelope = await _distribute_execute(
            content_id=str(uuid.uuid4()),
            subscription_id=str(uuid.uuid4()),
            tool_deps=tool_deps,
            _recipient_email_hint="leak-check@example.com",
            _recipient_phone_hint="13800001234",
        )

        # Outer wrapper status should be 'ok' (tool wrapper succeeded).
        assert envelope.get("status") == "ok"

        # The full envelope (incl. nested result) must not echo plaintext PII.
        assert not _contains_plaintext_pii(envelope), (
            f"distribute envelope leaks plaintext PII: {envelope!r}. "
            "T-097 facade must scrub recipient hints before returning."
        )

        # The facade result must surface canonical counters, not the stub's
        # `reason` field (which T-095 used to flag the stub).
        inner = envelope.get("result", {})
        assert "reason" not in inner or inner.get("status") == "ok", (
            f"stub-only 'reason' key still present: result={inner!r}. "
            "T-097 must drop the placeholder envelope."
        )

    async def test_distribute_pushrecord_recipient_id_is_masked_and_persisted(
        self,
    ) -> None:
        """Anti-regression (R-002): PushRepository.create must receive recipient_id
        and its value must be PII-masked (not plaintext email)."""
        from intellisource.storage.repositories.push import PushRepository

        tool_deps = _make_tool_deps_with_real_facade()
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        captured: list[dict[str, Any]] = []

        async def _spy_create(self_: object, **kwargs: Any) -> MagicMock:
            captured.append(kwargs)
            rec = MagicMock()
            rec.id = uuid.uuid4()
            return rec

        with patch.object(PushRepository, "create", new=_spy_create):
            await _distribute_execute(
                content_id=content_id,
                subscription_id=subscription_id,
                tool_deps=tool_deps,
            )

        assert len(captured) >= 1, (
            "PushRepository.create must be called; "
            "R-002 requires recipient_id to be persisted."
        )
        for idx, kw in enumerate(captured):
            assert "recipient_id" in kw, (
                f"call #{idx}: PushRepository.create must receive recipient_id kwarg; "
                f"got keys={list(kw.keys())}. R-002 not fixed."
            )
            rid = kw["recipient_id"]
            # Must not be plaintext email (mock sub has to_addr=user@example.com)
            assert not _EMAIL_PLAINTEXT_RE.search(str(rid or "")), (
                f"call #{idx}: recipient_id must be masked, got {rid!r}. "
                "R-002 facade must pass _mask_recipient() output to repo.create."
            )

    async def test_distribute_dedup_integrity_error_is_idempotent(self) -> None:
        """Anti-regression (R-004): when PushRepository.create raises IntegrityError
        (duplicate push record), facade must still return status='ok' rather than
        raising."""
        from sqlalchemy.exc import IntegrityError

        from intellisource.storage.repositories.push import PushRepository

        tool_deps = _make_tool_deps_with_real_facade()
        content_id = str(uuid.uuid4())
        subscription_id = str(uuid.uuid4())

        async def _raise_integrity(self_: object, **kwargs: Any) -> None:
            raise IntegrityError(
                statement="INSERT INTO push_records",
                params={},
                orig=Exception("uq_push_records_dedup"),
            )

        with patch.object(PushRepository, "create", new=_raise_integrity):
            envelope = await _distribute_execute(
                content_id=content_id,
                subscription_id=subscription_id,
                tool_deps=tool_deps,
            )

        # Facade must not propagate IntegrityError; outer tool envelope must be ok.
        assert envelope.get("status") == "ok", (
            f"distribute must not raise on IntegrityError from PushRepository; "
            f"got envelope={envelope!r}. R-004 idempotent dedup not in place."
        )
