"""LLM result cache using Redis.

Caches successful LLM call results to avoid duplicate API calls.
Cache key format: llm:cache:{call_type}:{prompt_version}:{content_fingerprint}
"""

from __future__ import annotations

import json
from typing import Any

from intellisource.llm.gateway import LLMResult
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)


class LLMCache:
    """Redis-based cache for LLM call results."""

    _KEY_PREFIX = "llm:cache"

    def __init__(self, redis: Any, ttl: int = 86400) -> None:
        """Initialize cache.

        Args:
            redis: Async Redis client (or any object with
                get/setex/keys/delete methods).
            ttl: Cache entry time-to-live in seconds (default 24h).
        """
        self._redis: Any = redis
        self._ttl = ttl

    def cache_key(
        self,
        content_fingerprint: str,
        call_type: str,
        prompt_version: str,
    ) -> str:
        """Generate cache key.

        Args:
            content_fingerprint: Hash of the input content.
            call_type: Type of LLM call (e.g. 'extract', 'summarize').
            prompt_version: Version identifier for the prompt template.

        Returns:
            Formatted cache key string.
        """
        return f"{self._KEY_PREFIX}:{call_type}:{prompt_version}:{content_fingerprint}"

    async def get(
        self,
        content_fingerprint: str,
        call_type: str,
        prompt_version: str,
    ) -> LLMResult | None:
        """Get cached result if exists.

        Args:
            content_fingerprint: Hash of the input content.
            call_type: Type of LLM call.
            prompt_version: Version identifier for the prompt template.

        Returns:
            Cached LLMResult or None if not found.
        """
        key = self.cache_key(content_fingerprint, call_type, prompt_version)
        try:
            raw: bytes | str | None = await self._redis.get(key)
            if raw is None:
                return None
            data: dict[str, Any] = json.loads(raw)
            return LLMResult(
                content=data["content"],
                metadata=data.get("metadata", {}),
            )
        except Exception:
            logger.warning("Cache get error for key '%s', treating as miss", key)
            return None

    async def set(
        self,
        content_fingerprint: str,
        call_type: str,
        prompt_version: str,
        result: LLMResult,
    ) -> None:
        """Cache a successful result.

        Args:
            content_fingerprint: Hash of the input content.
            call_type: Type of LLM call.
            prompt_version: Version identifier for the prompt template.
            result: The LLMResult to cache.
        """
        key = self.cache_key(content_fingerprint, call_type, prompt_version)
        payload = json.dumps({"content": result.content, "metadata": result.metadata})
        try:
            await self._redis.setex(key, self._ttl, payload)
        except Exception:
            logger.warning("Cache set error for key '%s', skipping", key)
