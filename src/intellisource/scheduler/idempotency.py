"""Idempotency guards: distributed lock + fingerprint dedup."""

from __future__ import annotations

from typing import Any

DEFAULT_LOCK_TTL: int = 300
LOCK_KEY_PREFIX: str = "idempotency:lock:"
RESULT_MARKER_PREFIX: str = "idempotency:result:"
# Marker outlives the broker visibility timeout (default 3600s) so a redelivery
# within that window still sees the task as already completed.
RESULT_MARKER_TTL: int = 86400


class IdempotencyGuard:
    """Distributed lock via Redis SET NX EX."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def acquire(self, source_id: str, ttl: int = DEFAULT_LOCK_TTL) -> bool:
        """Acquire lock. Returns True on success, False if already held."""
        key = LOCK_KEY_PREFIX + source_id
        result = await self._redis.set(key, "1", nx=True, ex=ttl)
        return result is not None

    async def release(self, source_id: str) -> None:
        """Release lock. Does not raise if key missing."""
        key = LOCK_KEY_PREFIX + source_id
        await self._redis.delete(key)

    async def mark_succeeded(
        self, source_id: str, ttl: int = RESULT_MARKER_TTL
    ) -> None:
        """Record a durable success marker so a later redelivery short-circuits.

        Plain SET (no NX) so a forced re-run refreshes the marker; the TTL
        outlives the broker visibility timeout so a redelivery inside that
        window still sees the completed state. Covers non-UUID lock keys
        (manual / source / fingerprint) that have no CollectTask row to consult.
        """
        await self._redis.set(RESULT_MARKER_PREFIX + source_id, "1", ex=ttl)

    async def was_succeeded(self, source_id: str) -> bool:
        """True when a success marker for this key is still live."""
        return await self._redis.get(RESULT_MARKER_PREFIX + source_id) is not None


class FingerprintChecker:
    """Content fingerprint deduplication."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def is_duplicate(self, fingerprint: str) -> bool:
        """Return True if fingerprint already exists."""
        result: bool = await self._repository.exists_by_fingerprint(fingerprint)
        return result

    async def record(self, fingerprint: str, content_id: Any) -> None:
        """Persist fingerprint-to-content_id mapping."""
        await self._repository.record_fingerprint(fingerprint, content_id)
