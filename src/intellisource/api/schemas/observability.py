"""Response schemas for LLM-status and system-health endpoints."""

from __future__ import annotations

from intellisource.api.schemas.common import APIModel


class QueueLengths(APIModel):
    """Interactive / background LLM queue depths."""

    interactive: int
    background: int


class LLMStatusResponse(APIModel):
    """LLM gateway health: circuit-breaker state + queue depths."""

    circuit_state: str
    queue_lengths: QueueLengths


class HealthResponse(APIModel):
    """Liveness/health payload. Extra keys (version, uptime_seconds, checks,
    timestamp, missing_config) are produced by the health checker and ride
    through unchanged."""

    status: str
