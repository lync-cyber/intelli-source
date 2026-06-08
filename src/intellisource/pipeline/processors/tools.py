"""Atomic processing tool functions.

Pure, non-LLM operations extracted from the former LLM processors.
These functions are registered as Agent-callable tools via AgentToolRegistry.
None of them depend on LLMGateway — they perform deterministic,
algorithmic processing only.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from intellisource.core.text_tools import filter_sensitive, truncate_for_push
from intellisource.observability.logging import get_logger
from intellisource.pipeline.digest.schemas import ContentDigest

logger = get_logger(__name__)

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
# truncate_fallback — pure, non-LLM cluster digest. The LLM summarize path
# lives in agent.tools.executes.summarize_cluster (pipeline ✗→ llm, Contract 2).
# ---------------------------------------------------------------------------


def truncate_fallback(cluster_contents: list[dict[str, str]]) -> ContentDigest:
    """First-3-sentence truncation digest."""
    if not cluster_contents:
        return ContentDigest(title="", summary="")
    title = cluster_contents[0].get("title", "")
    combined_text = " ".join(doc.get("body_text", "") for doc in cluster_contents)
    sentences = combined_text.split(". ")
    first_sentences = ". ".join(sentences[:3])
    if first_sentences and not first_sentences.endswith("."):
        first_sentences += "."

    return ContentDigest(title=title, summary=first_sentences)


# ---------------------------------------------------------------------------
# keyword_tag
# ---------------------------------------------------------------------------


async def keyword_tag(
    body_text: str,
    title: str,
    tag_library: list[str],
) -> list[str]:
    """Tag content by matching library keywords against title + body_text.

    Matching is a case-sensitive substring test (not word-boundary): the
    tag library is predominantly Chinese, which has no whitespace word
    boundaries, so an embedded tag must still match.

    Empty or whitespace-only library entries are skipped — ``"" in text`` is
    always True, so they would otherwise match every content and emit a
    meaningless tag. Matches preserve library order and are de-duplicated.

    Returns:
        List of matched tags, or ``[DEFAULT_KEYWORD_TAG]`` if none matched.
    """
    combined = body_text + " " + title
    seen: set[str] = set()
    matched: list[str] = []
    for tag in tag_library:
        if not tag.strip() or tag in seen:
            continue
        if tag in combined:
            seen.add(tag)
            matched.append(tag)
    if not matched:
        return [DEFAULT_KEYWORD_TAG]
    return matched


# filter_sensitive and truncate_for_push are re-exported from core.text_tools
# to preserve backward-compatible imports for callers of this module.
__all__ = [
    "filter_sensitive",
    "truncate_for_push",
]
