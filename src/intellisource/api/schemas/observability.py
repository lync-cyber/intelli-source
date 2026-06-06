"""Response schemas for LLM-status and system-health endpoints."""

from __future__ import annotations

from intellisource.api.schemas.common import APIModel


class LLMStatusResponse(APIModel):
    """LLM gateway health: circuit-breaker state."""

    circuit_state: str


class HealthResponse(APIModel):
    """Liveness/health payload. Extra keys (version, uptime_seconds, checks,
    timestamp, missing_config) are produced by the health checker and ride
    through unchanged."""

    status: str
