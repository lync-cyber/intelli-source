"""Dependency injection container for agent tool execute functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDeps:
    """Dependency container injected into all agent tool execute functions."""

    session_factory: Any
    llm_gateway: Any
    pipeline_engine: Any
    search_engine_factory: Any
    collector_registry: Any
    distributor: Any
