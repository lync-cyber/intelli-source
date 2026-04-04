"""Health check module for IntelliSource observability."""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class HealthResult:
    """Result of a health check run."""

    status: str
    version: str
    uptime_seconds: float
    checks: dict[str, str]
    timestamp: datetime


class HealthChecker:
    """Executes registered async health checks and aggregates results."""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[], Coroutine[Any, Any, bool]]] = {}
        self._start_time: float = time.monotonic()

    def register_check(
        self, name: str, check_fn: Callable[[], Coroutine[Any, Any, bool]]
    ) -> None:
        """Register an async health check function under *name*."""
        self._checks[name] = check_fn

    async def check_health(self) -> HealthResult:
        """Run all registered checks and return an aggregated ``HealthResult``."""
        checks: dict[str, str] = {}
        for name, fn in self._checks.items():
            try:
                healthy = await fn()
            except Exception:
                healthy = False
            checks[name] = "healthy" if healthy else "unhealthy"

        statuses = list(checks.values())
        if not statuses or all(s == "healthy" for s in statuses):
            status = "healthy"
        elif all(s == "unhealthy" for s in statuses):
            status = "unhealthy"
        else:
            status = "degraded"

        return HealthResult(
            status=status,
            version="0.3.0",
            uptime_seconds=time.monotonic() - self._start_time,
            checks=checks,
            timestamp=datetime.now(tz=timezone.utc),
        )
