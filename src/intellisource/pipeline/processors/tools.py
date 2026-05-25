"""Atomic processing tool functions.

Pure, non-LLM operations extracted from the former LLM processors.
These functions are registered as Agent-callable tools via AgentToolRegistry.
None of them depend on LLMGateway — they perform deterministic,
algorithmic processing only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_TAG: str = "未分类"

# ---------------------------------------------------------------------------
# regex_extract
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: list[tuple[str, re.Pattern[str], bool]] = [
    ("title", re.compile(r"Title:\s*(.+)"), False),
    ("authors", re.compile(r"Authors:\s*(.+)"), True),
    ("keywords", re.compile(r"Keywords:\s*(.+)"), True),
    ("date", re.compile(r"Date:\s*(.+)"), False),
]


async def regex_extract(
    body_text: str,
    patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract structured data from text using regex patterns.

    Args:
        body_text: Source text to extract from.
        patterns: Optional custom patterns. Each dict has keys
            ``field``, ``pattern`` (regex string), and ``is_list`` (bool).
            When *None*, built-in patterns for title/authors/keywords/date
            are used.

    Returns:
        Dict mapping field names to extracted values.
    """
    compiled: list[tuple[str, re.Pattern[str], bool]]
    if patterns is not None:
        compiled = [
            (p["field"], re.compile(p["pattern"]), bool(p.get("is_list", False)))
            for p in patterns
        ]
    else:
        compiled = _DEFAULT_PATTERNS

    result: dict[str, Any] = {}
    for field, pattern, is_list in compiled:
        match = pattern.search(body_text)
        if match:
            value = match.group(1).strip()
            result[field] = (
                [item.strip() for item in value.split(",")] if is_list else value
            )
    return result


# ---------------------------------------------------------------------------
# fingerprint_generate
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, strip, and collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


async def fingerprint_generate(title: str, body_text: str) -> str:
    """Return a stable SHA-256 hex digest of normalized title + body_text.

    Returns:
        64-character lowercase hex string.
    """
    normalized = _normalize(title) + _normalize(body_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# vector_search_similar
# ---------------------------------------------------------------------------


async def vector_search_similar(
    embedding: list[float],
    threshold: float,
    vector_store: Any,
) -> list[dict[str, Any]]:
    """Search for similar content via vector store.

    Args:
        embedding: Query embedding vector.
        threshold: Similarity threshold (0-1).
        vector_store: Vector store instance with ``search_similar`` method.

    Returns:
        List of candidate dicts (id, score, title, body_text).
    """
    candidates = await vector_store.search_similar(embedding, threshold=threshold)
    return [
        {
            "id": getattr(c, "id", None),
            "score": getattr(c, "score", None),
            "title": getattr(c, "title", ""),
            "body_text": getattr(c, "body_text", ""),
        }
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# fingerprint_dedup
# ---------------------------------------------------------------------------


async def fingerprint_dedup(
    title: str,
    body_text: str,
    known_fingerprints: list[str],
) -> dict[str, Any]:
    """Check if content is a duplicate by comparing SHA-256 fingerprints.

    Returns:
        Dict with ``is_duplicate`` (bool) and ``fingerprint`` (str).
    """
    fp = await fingerprint_generate(title, body_text)
    return {
        "is_duplicate": fp in known_fingerprints,
        "fingerprint": fp,
    }


# ---------------------------------------------------------------------------
# find_nearest_cluster
# ---------------------------------------------------------------------------


async def find_nearest_cluster(
    embedding: list[float],
    threshold: float,
    vector_store: Any,
) -> dict[str, Any] | None:
    """Find the nearest existing cluster for an embedding.

    Args:
        embedding: Content embedding vector.
        threshold: Cluster similarity threshold.
        vector_store: Vector store with ``find_nearest_cluster`` method.

    Returns:
        Dict with cluster ``id`` or *None* if no match.
    """
    cluster = await vector_store.find_nearest_cluster(embedding, threshold=threshold)
    if cluster is None:
        return None
    return {"id": getattr(cluster, "id", None)}


# ---------------------------------------------------------------------------
# tfidf_keywords
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "from",
        "that",
        "this",
        "it",
        "as",
        "not",
        "but",
        "its",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "about",
        "into",
        "than",
        "then",
        "no",
        "so",
        "up",
        "out",
        "if",
        "when",
        "which",
        "who",
        "whom",
        "what",
        "where",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
    }
)


async def tfidf_keywords(title: str, body_text: str) -> str:
    """Extract a TF-IDF-like topic string from title and body text.

    Returns:
        Space-separated top-5 keywords, or the title if no keywords found.
    """
    text = f"{title} {body_text}"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS and len(w) > 1]
    if not filtered:
        return title if title else "unknown"
    counts = Counter(filtered)
    top_words = [word for word, _ in counts.most_common(5)]
    return " ".join(top_words)


# ---------------------------------------------------------------------------
# truncate_summary
# ---------------------------------------------------------------------------


async def truncate_summary(
    cluster_contents: list[dict[str, str]],
    *,
    tool_deps: Any = None,
) -> dict[str, Any]:
    """Generate a digest from clustered documents.

    Attempts LLM-based summarization when ``tool_deps.llm_gateway`` is
    available; falls back to first-3-sentence truncation on failure.

    Args:
        cluster_contents: List of dicts with ``title``, ``body_text``,
            and optionally ``published_at``.
        tool_deps: Optional dependency container with ``llm_gateway``.

    Returns:
        Dict with title, summary, timeline, key_points.
    """
    if not cluster_contents:
        return {"title": "", "summary": "", "timeline": [], "key_points": []}

    gateway = getattr(tool_deps, "llm_gateway", None) if tool_deps is not None else None
    if gateway is not None:
        result = await _llm_summarize(cluster_contents, gateway)
        if result is not None:
            return result

    return _truncate_fallback(cluster_contents)


async def _llm_summarize(
    cluster_contents: list[dict[str, str]],
    gateway: Any,
) -> dict[str, Any] | None:
    """Call LLM to produce a structured summary; return None on failure."""
    docs_text = "\n\n".join(
        f"Title: {doc.get('title', '')}\n{doc.get('body_text', '')}"
        for doc in cluster_contents
    )
    try:
        from intellisource.llm.prompts import load_prompt  # noqa: PLC0415

        prompt = load_prompt("summarizer", style="structured", docs_text=docs_text)
        llm_result = await gateway.complete(
            prompt=prompt,
            task_type="summarize",
            response_format={"type": "json_object"},
        )
        parsed = json.loads(llm_result.content)
    except Exception:
        logger.warning("LLM summarize failed, falling back to truncation")
        return None

    required_keys = {"title", "summary", "timeline", "key_points"}
    if not required_keys.issubset(parsed.keys()):
        logger.warning("LLM response missing required keys, falling back")
        return None

    return {
        "title": str(parsed["title"]),
        "summary": str(parsed["summary"]),
        "timeline": list(parsed["timeline"]),
        "key_points": list(parsed["key_points"]),
    }


def _truncate_fallback(cluster_contents: list[dict[str, str]]) -> dict[str, Any]:
    """First-3-sentence truncation (original logic)."""
    title = cluster_contents[0].get("title", "")
    combined_text = " ".join(doc.get("body_text", "") for doc in cluster_contents)
    sentences = combined_text.split(". ")
    first_sentences = ". ".join(sentences[:3])
    if first_sentences and not first_sentences.endswith("."):
        first_sentences += "."

    return {
        "title": title,
        "summary": first_sentences,
        "timeline": [],
        "key_points": [],
    }


# ---------------------------------------------------------------------------
# keyword_tag
# ---------------------------------------------------------------------------


async def keyword_tag(
    body_text: str,
    title: str,
    tag_library: list[str],
) -> list[str]:
    """Tag content by matching keywords from a tag library.

    Returns:
        List of matched tags, or ``["未分类"]`` if none matched.
    """
    combined = body_text + " " + title
    matched = [tag for tag in tag_library if tag in combined]
    if not matched:
        return [DEFAULT_KEYWORD_TAG]
    return matched


# ---------------------------------------------------------------------------
# filter_sensitive
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# truncate_for_push
# ---------------------------------------------------------------------------


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
