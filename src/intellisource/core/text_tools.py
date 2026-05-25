"""Pure text utility functions shared across modules.

These are stateless, deterministic helpers used by both pipeline and
distributor layers without creating cross-layer dependencies.
"""

from __future__ import annotations


async def filter_sensitive(
    text: str,
    sensitive_words: list[str],
) -> list[str]:
    """Find sensitive words present in text.

    Returns:
        Deduplicated list of matched sensitive words.
    """
    if not text:
        return []
    text_lower = text.lower()
    return [w for w in sensitive_words if w.lower() in text_lower]


async def truncate_for_push(
    title: str,
    body_text: str,
) -> dict[str, str]:
    """Truncate content to reasonable push distribution lengths.

    Returns:
        Dict with ``title`` (max 80 chars) and ``summary`` (max 200 chars).
    """
    max_title_len = 80
    max_summary_len = 200
    opt_title = title[:max_title_len] if len(title) > max_title_len else title
    sentences = body_text.split(". ")
    summary = ". ".join(sentences[:3])
    if len(summary) > max_summary_len:
        summary = summary[:max_summary_len].rsplit(" ", 1)[0] + "..."
    return {"title": opt_title, "summary": summary}
