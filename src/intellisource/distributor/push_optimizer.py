"""Pre-push content optimization (F-010 / AC-047~049)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from intellisource.core.text_tools import filter_sensitive, truncate_for_push
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)

_MAX_TITLE_LEN = 80
_MAX_SUMMARY_LEN = 200


class PushOptimization(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=2000)


async def optimize_for_push(
    content: Any,
    subscription: Any,
    llm_gateway: Any,
) -> Any:
    """Return a push-ready content view with truncated/enhanced title and summary."""
    title = getattr(content, "title", "") or ""
    body = getattr(content, "body_text", "") or getattr(content, "summary", "") or ""

    truncated = await truncate_for_push(title=title, body_text=body)
    push_title = truncated["title"]
    push_summary = truncated["summary"]

    try:
        result = await llm_gateway.complete(
            prompt=(
                f"Subscription: {getattr(subscription, 'name', '')}\n"
                f"Original title: {title}\n"
                f"Body excerpt: {body[:800]}\n"
                f"Draft title: {push_title}\n"
                f"Draft summary: {push_summary}\n"
                "Return JSON with keys title (max 80 chars) and "
                "summary (max 200 chars) optimized for a push notification."
            ),
            task_type="push_optimize",
            response_format={"type": "json_object"},
        )
        parsed = json.loads(result.content)
        optimization = PushOptimization.model_validate(parsed)
        push_title = optimization.title[:_MAX_TITLE_LEN]
        push_summary = optimization.summary[:_MAX_SUMMARY_LEN]
    except (json.JSONDecodeError, ValidationError) as e:
        _logger.warning(
            "push_optimizer LLM output schema mismatch, falling back to original",
            extra={"error": repr(e), "raw_content": result.content[:200]},
        )
    except Exception:
        _logger.exception("LLM push optimize failed; using truncated content (AC-049)")

    sensitive = await filter_sensitive(
        text=f"{push_title} {push_summary}",
        sensitive_words=[],
    )
    if sensitive:
        _logger.warning(
            "push optimize produced sensitive terms %s; reverting to truncated content",
            sensitive,
        )
        push_title = truncated["title"]
        push_summary = truncated["summary"]

    return _overlay_push_fields(content, title=push_title, summary=push_summary)


def _overlay_push_fields(content: Any, *, title: str, summary: str) -> Any:
    """Shallow push view — DB ProcessedContent row is not mutated."""
    return SimpleNamespace(
        id=getattr(content, "id", None),
        title=title,
        summary=summary,
        body_text=getattr(content, "body_text", None),
        tags=getattr(content, "tags", []),
        source_url=getattr(content, "source_url", None),
        source_name=getattr(content, "source_name", None),
        published_at=getattr(content, "published_at", None),
    )
