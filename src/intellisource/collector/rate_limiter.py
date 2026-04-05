"""Token-bucket rate limiter backed by Redis."""

from __future__ import annotations

import asyncio
import time
from typing import Any

DEFAULT_QPS: int = 10
DEFAULT_CONCURRENCY: int = 5

# Lua script: token bucket with concurrency check.
# KEYS[1] = token bucket key, KEYS[2] = concurrency key
# ARGV[1] = qps (refill rate), ARGV[2] = concurrency limit, ARGV[3] = now (float)
_LUA_SCRIPT = """
local bucket_key = KEYS[1]
local conc_key = KEYS[2]
local qps = tonumber(ARGV[1])
local max_conc = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Token bucket
local data = redis.call('HMGET', bucket_key, 'tokens', 'last')
local tokens = tonumber(data[1]) or qps
local last = tonumber(data[2]) or now

local elapsed = now - last
tokens = math.min(qps, tokens + elapsed * qps)

-- Concurrency
local current_conc = tonumber(redis.call('GET', conc_key) or '0')
if tokens >= 1 and current_conc < max_conc then
    tokens = tokens - 1
    redis.call('HSET', bucket_key, 'tokens', tokens, 'last', now)
    redis.call('EXPIRE', bucket_key, 60)
    redis.call('INCR', conc_key)
    redis.call('EXPIRE', conc_key, 60)
    return 1
end
return 0
"""


class RateLimiter:
    """Redis-backed token bucket rate limiter with concurrency control."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def acquire(
        self,
        source_id: str,
        qps: int | None = None,
        concurrency: int | None = None,
    ) -> bool:
        """Acquire a rate-limit token for *source_id*.

        Blocks (waits) until a token is available rather than rejecting.
        Returns True when the token is granted.
        """
        effective_qps = qps if qps is not None else DEFAULT_QPS
        effective_conc = concurrency if concurrency is not None else DEFAULT_CONCURRENCY

        bucket_key = f"ratelimit:bucket:{source_id}"
        conc_key = f"ratelimit:conc:{source_id}"

        while True:
            now = time.time()
            result = await self._redis.eval(
                _LUA_SCRIPT,
                2,
                bucket_key,
                conc_key,
                effective_qps,
                effective_conc,
                now,
            )
            if result:
                return True
            await asyncio.sleep(1.0 / max(effective_qps, 1))

    async def release(self, source_id: str) -> None:
        """Release a concurrency slot for *source_id*."""
        conc_key = f"ratelimit:conc:{source_id}"
        await self._redis.eval(
            "local v = redis.call('DECR', KEYS[1]); "
            "if v < 0 then redis.call('SET', KEYS[1], 0) end; return v",
            1,
            conc_key,
        )
