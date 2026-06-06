"""MCP server exposing IntelliSource control-plane capabilities.

A thin Model Context Protocol adapter over the *same* domain services the REST
API and the agent tools use — ``PipelineDefinitionService`` /
``SourceConfigService`` / ``SubscriptionService`` / ``TemplateService`` plus the
read-only ``HybridSearchEngine`` and the content / task-chain repositories — so
the three transports stay behaviourally identical and logic lives only in the
services (north star).

Run as a stdio MCP server::

    python -m intellisource.mcp_server
    intellisource-mcp            # via the console_script entry point
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from intellisource.mcp_server._types import SearchEngineFactory, SessionFactory
from intellisource.mcp_server.tools import (
    register_pipeline_tools,
    register_search_tools,
    register_source_tools,
    register_subscription_tools,
    register_template_tools,
)
from intellisource.search.hybrid import HybridSearchEngine

__all__ = ["build_mcp_server", "main"]

_db_manager: Any = None


def _default_session_factory() -> Any:
    """Lazily build a process-wide DatabaseManager-backed session context."""
    global _db_manager
    if _db_manager is None:
        from intellisource.storage.database import DatabaseManager

        _db_manager = DatabaseManager()
    return _db_manager.get_session()


def _default_search_engine_factory(session: AsyncSession) -> HybridSearchEngine:
    return HybridSearchEngine(session)


def build_mcp_server(
    session_factory: SessionFactory | None = None,
    *,
    search_engine_factory: SearchEngineFactory | None = None,
) -> FastMCP:
    """Build a FastMCP server whose tools delegate to the domain services."""
    mcp = FastMCP("intellisource")
    session_cm: SessionFactory = session_factory or _default_session_factory
    search_factory: SearchEngineFactory = (
        search_engine_factory or _default_search_engine_factory
    )

    register_pipeline_tools(mcp, session_cm)
    register_source_tools(mcp, session_cm)
    register_subscription_tools(mcp, session_cm)
    register_search_tools(mcp, session_cm, search_factory)
    register_template_tools(mcp, session_cm)
    return mcp


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    build_mcp_server().run(transport="stdio")
