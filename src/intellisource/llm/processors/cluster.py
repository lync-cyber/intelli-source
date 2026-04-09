"""ContentClusterer: cluster assignment processor.

Uses vector similarity and LLM topic generation.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from intellisource.llm.processors._async_compat import run_async
from intellisource.llm.prompts import load_prompt
from intellisource.pipeline.base import BaseProcessor
from intellisource.pipeline.context import PipelineContext


class ContentClusterer(BaseProcessor):
    """Assign content to clusters based on embedding similarity.

    Joins an existing cluster when vector store finds a match above threshold,
    otherwise creates a new cluster with an LLM-generated topic (or TF-IDF fallback).
    """

    def __init__(
        self,
        gateway: Any,
        vector_store: Any,
        call_log: Any,
        cluster_threshold: float = 0.75,
    ) -> None:
        self._gateway = gateway
        self._vector_store = vector_store
        self._call_log = call_log
        self.cluster_threshold = cluster_threshold
        self._last_method: str = ""

    def process(self, context: PipelineContext) -> PipelineContext:
        """Process context to assign content to a cluster.

        Args:
            context: Pipeline context containing embedding, title, body_text.

        Returns:
            Updated context with cluster_id and optional
            cluster_topic, cluster_method.

        Raises:
            ValueError: If embedding is missing from context.
        """
        embedding = context.get("embedding")
        if embedding is None:
            raise ValueError("embedding is required in context")

        title = context.get("title", "")
        body_text = context.get("body_text", "")

        # Try to find an existing cluster
        cluster = None
        try:
            cluster = self._vector_store.find_nearest_cluster(
                embedding, threshold=self.cluster_threshold
            )
        except Exception:
            cluster = None

        if cluster is not None:
            # Join existing cluster
            context.set("cluster_id", cluster.id)
            self._vector_store.update_centroid(cluster.id, embedding)
        else:
            # Create new cluster
            self._last_method = ""
            topic = self._generate_topic(title, body_text)
            new_cluster = self._vector_store.create_cluster(embedding, topic=topic)
            context.set("cluster_id", new_cluster.id)
            context.set("cluster_topic", topic)
            context.set("cluster_method", self._last_method)
            if self._last_method == "tfidf":
                context.set("cluster_fallback", True)

        return context

    def _generate_topic(self, title: str, body_text: str) -> str:
        """Generate a cluster topic using LLM, falling back to TF-IDF on failure."""
        try:
            prompt = load_prompt("cluster", title=title, body_text=body_text)
            result = run_async(self._gateway.complete(prompt))
            run_async(
                self._call_log.record(
                    call_type="cluster",
                    status="success",
                    input_tokens=result.metadata.get("input_tokens", 0),
                    output_tokens=result.metadata.get("output_tokens", 0),
                    metadata=result.metadata,
                )
            )
            self._last_method = "llm"
            content: str = result.content
            return content
        except Exception:
            # Fallback to TF-IDF keywords
            self._last_method = "tfidf"
            return self._tfidf_topic(title, body_text)

    @staticmethod
    def _tfidf_topic(title: str, body_text: str) -> str:
        """Extract a simple TF-IDF-like topic from title and body text."""
        text = f"{title} {body_text}"
        words = re.findall(r"[a-zA-Z]+", text.lower())
        stop_words = {
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
        filtered = [w for w in words if w not in stop_words and len(w) > 1]
        if not filtered:
            return title if title else "unknown"
        counts = Counter(filtered)
        top_words = [word for word, _ in counts.most_common(5)]
        return " ".join(top_words)
