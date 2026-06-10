"""Process tool execute function."""

from __future__ import annotations

import asyncio
import uuid as _uuid
from typing import Any

from intellisource.agent.deps import ToolDeps
from intellisource.agent.tool_results import ProcessItemResult
from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.results import tool_degraded
from intellisource.observability.logging import get_logger
from intellisource.storage import EMBEDDING_DIM

logger = get_logger(__name__)


async def _process_execute(
    content_id: str = "",
    raw_content_ids: list[str] | None = None,
    tool_deps: ToolDeps | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch RawContent, run PipelineEngine, persist ProcessedContent.

    When ``raw_content_ids`` is provided the function fans-out over the full
    list; ``content_id`` is used as a single-item fallback for backward
    compatibility.
    """
    if tool_deps is None or tool_deps.pipeline_engine is None:
        logger.warning("tool_deps not injected for process, returning placeholder")
        return tool_degraded("process", "tool_deps not injected", content_id=content_id)

    if tool_deps.session_factory is None:
        logger.warning(
            "session_factory not injected for process, returning placeholder"
        )
        return tool_degraded(
            "process", "session_factory not injected", content_id=content_id
        )

    ids_to_process: list[str] = (
        raw_content_ids if raw_content_ids else ([content_id] if content_id else [])
    )

    if not ids_to_process:
        return tool_degraded("process", "no content_id provided", content_id=content_id)

    from datetime import datetime, timezone  # noqa: PLC0415

    from intellisource.core.processor import PipelineContext  # noqa: PLC0415
    from intellisource.storage.repositories.content import (  # noqa: PLC0415
        ContentRepository,
    )
    from intellisource.storage.repositories.source import (  # noqa: PLC0415
        SourceRepository,
    )

    processed_content_ids: list[str] = []
    results: list[ProcessItemResult] = []

    for cid in ids_to_process:
        try:
            raw_id = _uuid.UUID(cid)
        except ValueError:
            results.append(
                {
                    "status": "degraded",
                    "reason": f"invalid content_id: {cid!r}",
                    "content_id": cid,
                }
            )
            continue

        ctx = PipelineContext()
        ctx.set("content_id", cid)

        async with tool_deps.session_factory() as session:
            repo = ContentRepository(session=session)
            raw = await repo.get_raw_by_id(raw_id)
            if raw is None:
                results.append(
                    {
                        "status": "degraded",
                        "reason": f"RawContent not found: {cid}",
                        "content_id": cid,
                    }
                )
                continue

            ctx.set("body_html", raw.body_html or "")
            ctx.set("body_text", raw.body_text or "")
            ctx.set("title", raw.title or "")
            ctx.set("fingerprint", raw.fingerprint or "")
            ctx.set("content_id", str(raw.id))
            ctx.set("published_at", raw.published_at)

            ctx = await asyncio.to_thread(tool_deps.pipeline_engine.execute, ctx)

            tags_val = ctx.get("tags")
            tags: list[str] = tags_val if isinstance(tags_val, list) else []

            discipline_tags: list[str] = []
            source_name: str | None = None
            if isinstance(raw.source_id, _uuid.UUID):
                source = await SourceRepository(session).get_by_id(raw.source_id)
                if source is not None:
                    discipline_tags = list(source.discipline_tags)
                    source_name = source.name

            existing_processed = await repo.get_processed_by_raw_id(raw_id)
            if existing_processed is not None:
                embedding_val = ctx.get("embedding")
                if (
                    isinstance(embedding_val, list)
                    and len(embedding_val) == EMBEDDING_DIM
                    and existing_processed.embedding is None
                ):
                    updated = await repo.update(
                        existing_processed.id, embedding=embedding_val
                    )
                    processed = updated if updated is not None else existing_processed
                else:
                    processed = existing_processed
            else:
                embedding_val = ctx.get("embedding")
                embedding_arg: list[float] | None = (
                    embedding_val if isinstance(embedding_val, list) else None
                )
                processed = await repo.create(
                    raw_content_id=raw_id,
                    title=str(ctx.get("title") or raw.title or ""),
                    body_text=str(ctx.get("body_text") or raw.body_text or ""),
                    summary=str(ctx.get("summary") or ""),
                    tags=tags,
                    discipline_tags=discipline_tags,
                    source_name=source_name,
                    embedding=embedding_arg,
                    fingerprint=str(ctx.get("fingerprint") or raw.fingerprint or ""),
                    source_url=raw.source_url,
                    structured_data=ctx.get("digest"),
                    processing_status="completed",
                    processed_at=datetime.now(tz=timezone.utc),
                    published_at=(
                        ctx.get("published_at") or raw.published_at or raw.created_at
                    ),
                )

            raw.status = "processed"
            raw.processed_at = datetime.now(tz=timezone.utc)
            await session.commit()

        processed_id = str(processed.id)
        processed_content_ids.append(processed_id)
        results.append(
            {
                "body_html": ctx.get("body_html"),
                "body_text": ctx.get("body_text"),
                "title": ctx.get("title"),
                "fingerprint": ctx.get("fingerprint"),
                "content_id": processed_id,
                "raw_content_id": str(raw_id),
            }
        )

    first_processed_id = (
        processed_content_ids[0] if processed_content_ids else content_id
    )
    return {
        "status": "ok",
        "tool": "process",
        "results": results,
        "processed_content_ids": processed_content_ids,
        "content_id": first_processed_id,
    }


PROCESS_TOOL_DEF = ToolDefinition(
    name="process",
    description="Process raw content through the cleaning/extraction pipeline.",
    parameters={
        "type": "object",
        "properties": {
            "content_id": {
                "type": "string",
                "description": "Single raw content UUID to process.",
            },
            "raw_content_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Batch of raw content UUIDs; takes precedence over"
                    " content_id when provided."
                ),
            },
        },
        # At least one content identifier must be supplied (single id or
        # the batch list); a call with neither is a no-op.
        "anyOf": [
            {"required": ["content_id"]},
            {"required": ["raw_content_ids"]},
        ],
    },
    execute=_process_execute,
    mutates_external_state=True,
)
