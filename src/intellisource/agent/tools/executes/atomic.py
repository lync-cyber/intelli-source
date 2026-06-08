"""Atomic processing tool descriptors + the ``llm_complete`` meta-tool.

These descriptors wire the stateless processing functions from
``intellisource.pipeline.processors.tools`` (regex / fingerprint / vector /
keyword / truncation helpers) as agent-callable tools, plus the
``_summarize_cluster_execute`` digest tool and the ``_llm_complete_execute``
meta-tool. The execute callables live in the pipeline layer (pure helpers) and
in ``executes.summarize_cluster`` / ``executes.llm``; this module only assembles
their ``ToolDefinition`` list so the registry can install them via
``register_atomic_tools``.
"""

from __future__ import annotations

from intellisource.agent.tools._spec import ToolDefinition
from intellisource.agent.tools.executes.llm import _llm_complete_execute
from intellisource.agent.tools.executes.summarize_cluster import (
    _summarize_cluster_execute,
)
from intellisource.pipeline.processors import tools as atomic_tools

ATOMIC_TOOL_DEFS: list[ToolDefinition] = [
    ToolDefinition(
        name="regex_extract",
        description="Extract structured data from text using regex patterns.",
        parameters={
            "type": "object",
            "properties": {
                "body_text": {"type": "string"},
                "patterns": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["body_text"],
        },
        execute=atomic_tools.regex_extract,
    ),
    ToolDefinition(
        name="fingerprint_generate",
        description="Generate a SHA-256 fingerprint from title and body text.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_text": {"type": "string"},
            },
            "required": ["title", "body_text"],
        },
        execute=atomic_tools.fingerprint_generate,
    ),
    ToolDefinition(
        name="vector_search_similar",
        description="Search for similar content via vector store.",
        parameters={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "threshold": {"type": "number"},
                "vector_store": {"type": "object"},
            },
            "required": ["embedding", "threshold", "vector_store"],
        },
        execute=atomic_tools.vector_search_similar,
    ),
    ToolDefinition(
        name="fingerprint_dedup",
        description="Check if content is a duplicate by SHA-256 fingerprint.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_text": {"type": "string"},
                "known_fingerprints": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["title", "body_text", "known_fingerprints"],
        },
        execute=atomic_tools.fingerprint_dedup,
    ),
    ToolDefinition(
        name="find_nearest_cluster",
        description="Find the nearest existing cluster for an embedding.",
        parameters={
            "type": "object",
            "properties": {
                "embedding": {"type": "array", "items": {"type": "number"}},
                "threshold": {"type": "number"},
                "vector_store": {"type": "object"},
            },
            "required": ["embedding", "threshold", "vector_store"],
        },
        execute=atomic_tools.find_nearest_cluster,
    ),
    ToolDefinition(
        name="tfidf_keywords",
        description="Extract TF-IDF-like top-5 keywords from title and body.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_text": {"type": "string"},
            },
            "required": ["title", "body_text"],
        },
        execute=atomic_tools.tfidf_keywords,
    ),
    ToolDefinition(
        # ``truncate_summary`` is a load-bearing tool name: it is referenced
        # by config/pipelines/*.yaml and persisted in pipeline ``tools_allowed``
        # rows, so renaming it requires a coordinated YAML + DB migration. The
        # primary behaviour is LLM summarization (truncation is only the
        # fallback), as the description makes explicit.
        name="truncate_summary",
        description=(
            "Generate a structured digest from clustered documents"
            " using LLM summarization with truncation fallback."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster_contents": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["cluster_contents"],
        },
        execute=_summarize_cluster_execute,
    ),
    ToolDefinition(
        name="keyword_tag",
        description="Tag content by matching keywords from a tag library.",
        parameters={
            "type": "object",
            "properties": {
                "body_text": {"type": "string"},
                "title": {"type": "string"},
                "tag_library": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["body_text", "title", "tag_library"],
        },
        execute=atomic_tools.keyword_tag,
    ),
    ToolDefinition(
        name="filter_sensitive",
        description="Find sensitive words present in text.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "sensitive_words": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["text", "sensitive_words"],
        },
        execute=atomic_tools.filter_sensitive,
    ),
    ToolDefinition(
        name="truncate_for_push",
        description="Truncate content to push distribution lengths.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_text": {"type": "string"},
            },
            "required": ["title", "body_text"],
        },
        execute=atomic_tools.truncate_for_push,
    ),
    ToolDefinition(
        name="llm_complete",
        description=(
            "Meta-tool: invoke LLM for a specific call_type with prompt variables."
        ),
        parameters={
            "type": "object",
            "properties": {
                "call_type": {"type": "string"},
                "prompt_vars": {"type": "object"},
            },
            "required": ["call_type", "prompt_vars"],
        },
        execute=_llm_complete_execute,
    ),
]
