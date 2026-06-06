"""Read-only knowledge-base search + content-detail MCP tools."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from intellisource.mcp_server._serialize import search_response_dict
from intellisource.mcp_server._types import SearchEngineFactory, SessionFactory
from intellisource.observability.logging import get_logger
from intellisource.storage.repositories.content import ContentRepository

logger = get_logger(__name__)


def register_search_tools(
    mcp: FastMCP,
    session_cm: SessionFactory,
    search_factory: SearchEngineFactory,
) -> None:
    @mcp.tool(
        name="search",
        description=(
            "Search the knowledge base (hybrid keyword + semantic). Params: query"
            " (non-empty str), top_k (int). Returns {items:[{content_id, title,"
            " snippet, score, source_name, published_at}], total, query_time_ms},"
            " or {error:'invalid_input'} for an empty query. Read-only."
        ),
    )
    async def search(query: str, top_k: int = 10) -> dict[str, Any]:
        if not query:
            return {"error": "invalid_input", "reason": "query must not be empty"}
        try:
            async with session_cm() as session:
                engine = search_factory(session)
                response = await engine.search(query=query, limit=top_k)
        except ValueError as exc:
            return {"error": "invalid_input", "reason": str(exc)}
        except Exception as exc:
            logger.warning("mcp search failed: %s", exc)
            return {"error": "error", "reason": str(exc)}
        return search_response_dict(response)

    @mcp.tool(
        name="get_content_detail",
        description=(
            "Fetch one processed content row by id. Params: content_id (UUID"
            " str). Returns {id, title, summary, tags, source_name, source_url,"
            " published_at, processing_status} or {error:'not_found'}. Read-only."
        ),
    )
    async def get_content_detail(content_id: str) -> dict[str, Any]:
        try:
            cid = _uuid.UUID(content_id)
        except ValueError:
            return {
                "error": "invalid_input",
                "reason": f"bad content_id: {content_id!r}",
            }
        async with session_cm() as session:
            row = await ContentRepository(session).get_by_id(cid)
        if row is None:
            return {"error": "not_found", "content_id": content_id}
        return {
            "id": str(row.id),
            "title": row.title,
            "summary": row.summary,
            "tags": list(row.tags or []),
            "source_name": row.source_name,
            "source_url": row.source_url,
            "published_at": (
                row.published_at.isoformat() if row.published_at else None
            ),
            "processing_status": row.processing_status,
        }
