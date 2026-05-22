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
from typing import Any
from unittest.mock import MagicMock, patch

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


def _make_tool_deps_with_real_facade() -> ToolDeps:
    """ToolDeps backed by the production build_distributor_facade.

    Currently this resolves to the T-095 stub; after T-097 GREEN it must be
    the real DistributorFacade in distributor/facade.py.
    """
    session_factory = MagicMock(name="session_factory")
    redis_client = MagicMock(name="redis_client")
    facade = build_distributor_facade(session_factory, redis_client)
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
