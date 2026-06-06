"""Idempotency guards: distributed lock + fingerprint dedup."""

from __future__ import annotations

from typing import Any

DEFAULT_LOCK_TTL: int = 300
LOCK_KEY_PREFIX: str = "idempotency:lock:"


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
