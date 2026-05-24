"""Search, content detail, and summarize tool execute functions."""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

logger = logging.getLogger(__name__)


async def _search_execute(
    query: str = "",
    top_k: int = 10,
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke HybridSearchEngine.search() with the given query."""
    if tool_deps is None:
        factory = None
        session_factory = None
    else:
        factory = getattr(tool_deps, "search_engine_factory", None)
        session_factory = getattr(tool_deps, "session_factory", None)
    if factory is not None and session_factory is not None:
        async with session_factory() as session:
            engine = factory(session)
            response = await engine.search(query=query, limit=top_k, **kwargs)
        return {
            "status": "ok",
            "tool": "search",
            "response": _serialize_search_response(response),
        }
    logger.warning("tool_deps not injected for search, returning placeholder")
    return {
        "status": "degraded",
        "tool": "search",
        "reason": "tool_deps not injected",
        "query": query,
    }


def _serialize_search_response(response: Any) -> dict[str, Any]:
    """Convert HybridSearchEngine SearchResponse to a JSON-friendly dict."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(response) and not isinstance(response, type):
        payload = asdict(response)
        items = payload.get("items") or []
        serialized_items: list[dict[str, Any]] = []
        for item in items:
            if is_dataclass(item) and not isinstance(item, type):
                row = asdict(item)
            elif isinstance(item, dict):
                row = dict(item)
            else:
                continue
            content_id = row.get("content_id")
            if content_id is not None:
                row["content_id"] = str(content_id)
            serialized_items.append(row)
        payload["items"] = serialized_items
        return payload
    if isinstance(response, dict):
        return response
    return {"items": [], "total": 0, "query_time_ms": 0}


async def _get_content_detail_execute(
    content_id: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke ContentRepository.get_by_id() for the given content_id."""
    from intellisource.agent.dto import ProcessedContentDTO  # noqa: PLC0415
    from intellisource.storage.repositories.content import (
        ContentRepository,  # noqa: PLC0415
    )

    if tool_deps is not None and tool_deps.session_factory is not None:
        session = tool_deps.session_factory()
        async with session as s:
            repo = ContentRepository(session=s)
            content = await repo.get_by_id(_uuid.UUID(content_id))
            if content is None:
                return {
                    "status": "degraded",
                    "tool": "get_content_detail",
                    "reason": f"content not found: {content_id}",
                    "content_id": content_id,
                }
            content_dict = ProcessedContentDTO.model_validate(content).model_dump(
                mode="json"
            )
            return {
                "status": "ok",
                "tool": "get_content_detail",
                "content": content_dict,
                "content_id": content_id,
            }
    logger.warning(
        "tool_deps not injected for get_content_detail, returning placeholder"
    )
    return {
        "status": "degraded",
        "tool": "get_content_detail",
        "reason": "tool_deps not injected",
        "content_id": content_id,
    }


async def _summarize_for_user_execute(
    content_id: str = "",
    content: str = "",
    tool_deps: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke LLMGateway.complete() to generate a user-facing summary."""
    if tool_deps is not None and tool_deps.llm_gateway is not None:
        prompt = f"Summarize the following content:\n\n{content}"
        result = await tool_deps.llm_gateway.complete(
            prompt=prompt, task_type="summarize"
        )
        return {
            "status": "ok",
            "tool": "summarize_for_user",
            "summary": result.content,
            "content_id": content_id,
        }
    logger.warning(
        "tool_deps not injected for summarize_for_user, returning placeholder"
    )
    return {
        "status": "degraded",
        "tool": "summarize_for_user",
        "reason": "tool_deps not injected",
        "content_id": content_id,
    }
