"""Tests for idempotency module.

Covers:
- AC-036: Multi-worker concurrent execution without duplicate processing.
- AC-037: Idempotency design covers fingerprint dedup + push record +
          distributed lock (three layers).
- AC-T029-1: IdempotencyGuard.acquire(source_id) acquires distributed lock
             via Redis SET NX EX, preventing concurrent collection on same
             source.
- AC-T029-2: Lock auto-expires after default 5 minutes (300s) to prevent
             deadlocks.
- AC-T029-3: Fingerprint dedup checks RawContent.fingerprint unique
             constraint before insert.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# -------------------------------------------------------------------
# Lazy imports (RED phase: module does not exist yet)
# -------------------------------------------------------------------


def _import_idempotency():
    """Lazy import of the idempotency module under test.

    Raises ``ModuleNotFoundError`` when the implementation does not
    yet exist -- the expected RED state.
    """
    import intellisource.scheduler.idempotency as mod

    return mod


def _make_guard(redis_mock):
    """Instantiate IdempotencyGuard with a mock Redis client."""
    mod = _import_idempotency()
    return mod.IdempotencyGuard(redis=redis_mock)


def _make_fingerprint_checker(repo_mock):
    """Instantiate FingerprintChecker with a mock repository."""
    mod = _import_idempotency()
    return mod.FingerprintChecker(repository=repo_mock)


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------


@pytest.fixture()
def mock_redis():
    """Provide a mock async Redis client."""
    r = MagicMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.delete = AsyncMock(return_value=1)
    return r


@pytest.fixture()
def mock_content_repo():
    """Provide a mock fingerprint repository."""
    repo = MagicMock()
    repo.exists_by_fingerprint = AsyncMock(return_value=False)
    repo.record_fingerprint = AsyncMock(return_value=None)
    return repo


# ===================================================================
# Constants
# ===================================================================


class TestConstants:
    """Verify module-level constants are defined correctly."""

    def test_default_lock_ttl(self):
        """DEFAULT_LOCK_TTL must equal 300 (5 minutes)."""
        mod = _import_idempotency()
        assert mod.DEFAULT_LOCK_TTL == 300

    def test_lock_key_prefix(self):
        """LOCK_KEY_PREFIX must be 'idempotency:lock:'."""
        mod = _import_idempotency()
        assert mod.LOCK_KEY_PREFIX == "idempotency:lock:"


# ===================================================================
# IdempotencyGuard — distributed lock (AC-T029-1, AC-T029-2, AC-036)
# ===================================================================


class TestIdempotencyGuardAcquire:
    """AC-T029-1: acquire(source_id) obtains a distributed lock."""

    @pytest.mark.asyncio
    async def test_acquire_success(self, mock_redis):
        """First acquire on a source_id should return True."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        result = await guard.acquire("source-abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_uses_set_nx_ex(self, mock_redis):
        """acquire must call Redis SET with NX and EX flags."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        await guard.acquire("source-123")
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        # Key should include the prefix
        key_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("name")
        assert "idempotency:lock:" in str(key_arg)
        # NX and EX must be set
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        assert kwargs.get("nx") is True or kwargs.get("NX") is True
        assert kwargs.get("ex") == 300 or kwargs.get("EX") == 300

    @pytest.mark.asyncio
    async def test_acquire_already_locked(self, mock_redis):
        """When lock already held, acquire should return False."""
        mock_redis.set = AsyncMock(return_value=None)  # SET NX returns None on failure
        guard = _make_guard(mock_redis)
        result = await guard.acquire("source-abc")
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_concurrent_same_source(self, mock_redis):
        """AC-036: Two concurrent acquires on same source_id — only one succeeds."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return True if call_count == 1 else None

        mock_redis.set = AsyncMock(side_effect=side_effect)
        guard = _make_guard(mock_redis)

        first = await guard.acquire("source-dup")
        second = await guard.acquire("source-dup")

        assert first is True
        assert second is False


class TestIdempotencyGuardTTL:
    """AC-T029-2: Lock auto-expires after default TTL (300s)."""

    @pytest.mark.asyncio
    async def test_default_ttl_is_300(self, mock_redis):
        """Without explicit ttl, acquire should use 300s."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        await guard.acquire("source-ttl")
        call_kwargs = mock_redis.set.call_args[1] or {}
        ttl_value = call_kwargs.get("ex") or call_kwargs.get("EX")
        assert ttl_value == 300

    @pytest.mark.asyncio
    async def test_custom_ttl(self, mock_redis):
        """Explicit ttl parameter should override the default."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        await guard.acquire("source-custom", ttl=60)
        call_kwargs = mock_redis.set.call_args[1] or {}
        ttl_value = call_kwargs.get("ex") or call_kwargs.get("EX")
        assert ttl_value == 60


class TestIdempotencyGuardRelease:
    """IdempotencyGuard.release(source_id) removes the lock."""

    @pytest.mark.asyncio
    async def test_release_deletes_key(self, mock_redis):
        """release should delete the lock key from Redis."""
        mock_redis.delete = AsyncMock(return_value=1)
        guard = _make_guard(mock_redis)
        await guard.release("source-rel")
        mock_redis.delete.assert_called_once()
        key_arg = mock_redis.delete.call_args[0][0]
        assert "idempotency:lock:" in str(key_arg)

    @pytest.mark.asyncio
    async def test_release_nonexistent_key(self, mock_redis):
        """Releasing a non-held lock should not raise."""
        mock_redis.delete = AsyncMock(return_value=0)
        guard = _make_guard(mock_redis)
        # Should not raise
        await guard.release("source-missing")


class TestIdempotencyGuardSuccessMarker:
    """durable success marker covers non-UUID lock-key redelivery."""

    def test_result_marker_constants(self):
        """RESULT_MARKER_PREFIX + a TTL outliving the broker visibility timeout."""
        mod = _import_idempotency()
        assert mod.RESULT_MARKER_PREFIX == "idempotency:result:"
        # Default broker visibility timeout is 3600s; the marker must outlive it
        # so a redelivery inside that window still sees "already done".
        assert mod.RESULT_MARKER_TTL > 3600

    @pytest.mark.asyncio
    async def test_mark_succeeded_sets_result_key_with_long_ttl(self, mock_redis):
        """mark_succeeded writes a result marker keyed by the lock key + TTL."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        await guard.mark_succeeded("news_collect:source:s1")
        mock_redis.set.assert_called_once()
        key_arg = mock_redis.set.call_args[0][0]
        assert "idempotency:result:" in str(key_arg)
        kwargs = mock_redis.set.call_args[1] or {}
        assert (kwargs.get("ex") or kwargs.get("EX") or 0) > 3600

    @pytest.mark.asyncio
    async def test_mark_succeeded_overwrites_not_nx(self, mock_redis):
        """A forced re-run refreshes the marker, so SET must not be NX-guarded."""
        mock_redis.set = AsyncMock(return_value=True)
        guard = _make_guard(mock_redis)
        await guard.mark_succeeded("k")
        kwargs = mock_redis.set.call_args[1] or {}
        assert not kwargs.get("nx")

    @pytest.mark.asyncio
    async def test_was_succeeded_true_when_marker_present(self, mock_redis):
        """A live marker means the task already completed."""
        mock_redis.get = AsyncMock(return_value="1")
        guard = _make_guard(mock_redis)
        result = await guard.was_succeeded("news_collect:source:s1")
        assert result is True
        key_arg = mock_redis.get.call_args[0][0]
        assert "idempotency:result:" in str(key_arg)

    @pytest.mark.asyncio
    async def test_was_succeeded_false_when_marker_absent(self, mock_redis):
        """No marker means the task has not completed under this key."""
        mock_redis.get = AsyncMock(return_value=None)
        guard = _make_guard(mock_redis)
        result = await guard.was_succeeded("k")
        assert result is False


# ===================================================================
# FingerprintChecker — content fingerprint dedup (AC-T029-3)
# ===================================================================


class TestFingerprintCheckerIsDuplicate:
    """AC-T029-3: Check RawContent.fingerprint uniqueness before insert."""

    @pytest.mark.asyncio
    async def test_not_duplicate(self, mock_content_repo):
        """New fingerprint should return False (not a duplicate)."""
        mock_content_repo.exists_by_fingerprint = AsyncMock(return_value=False)
        checker = _make_fingerprint_checker(mock_content_repo)
        result = await checker.is_duplicate("sha256-abc123")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_duplicate(self, mock_content_repo):
        """Existing fingerprint should return True."""
        mock_content_repo.exists_by_fingerprint = AsyncMock(return_value=True)
        checker = _make_fingerprint_checker(mock_content_repo)
        result = await checker.is_duplicate("sha256-abc123")
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_fingerprint(self, mock_content_repo):
        """Empty fingerprint string should still be checked."""
        mock_content_repo.exists_by_fingerprint = AsyncMock(return_value=False)
        checker = _make_fingerprint_checker(mock_content_repo)
        result = await checker.is_duplicate("")
        assert result is False


class TestFingerprintCheckerRecord:
    """FingerprintChecker.record() persists fingerprint mapping."""

    @pytest.mark.asyncio
    async def test_record_fingerprint(self, mock_content_repo):
        """record should store fingerprint-to-content_id mapping."""
        content_id = uuid.uuid4()
        checker = _make_fingerprint_checker(mock_content_repo)
        await checker.record("sha256-new", content_id)
        mock_content_repo.record_fingerprint.assert_called_once_with(
            "sha256-new", content_id
        )


# ===================================================================
# Integration-style: idempotency layers (AC-037)
# ===================================================================


class TestThreeLayerIdempotency:
    """AC-037: dedup layers exist and are independently usable."""

    def test_all_classes_importable(self):
        """The module must export the lock + fingerprint dedup classes."""
        mod = _import_idempotency()
        assert hasattr(mod, "IdempotencyGuard")
        assert hasattr(mod, "FingerprintChecker")

    @pytest.mark.asyncio
    async def test_guard_and_fingerprint_independent(
        self, mock_redis, mock_content_repo
    ):
        """Lock layer and fingerprint layer operate independently."""
        guard = _make_guard(mock_redis)
        checker = _make_fingerprint_checker(mock_content_repo)

        # Acquire lock
        mock_redis.set = AsyncMock(return_value=True)
        locked = await guard.acquire("source-x")
        assert locked is True

        # Fingerprint check is a separate concern
        mock_content_repo.exists_by_fingerprint = AsyncMock(return_value=False)
        is_dup = await checker.is_duplicate("fp-123")
        assert is_dup is False
