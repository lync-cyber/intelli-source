"""Prompt builder with built-in token truncation.

Provides PromptBuilder for unified prompt assembly, reusing the existing
template loading infrastructure from intellisource.llm.prompts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import litellm

from intellisource.llm.prompts import _TEMPLATE_DIR, load_prompt, read_prompt_source
from intellisource.observability.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_UNKNOWN_VERSION = "unknown"

# (path_str, mtime_ns) -> sha256[:8]
_VERSION_CACHE: dict[tuple[str, int], str] = {}


def _resolve_template_path(call_type: str, style: str | None) -> Path:
    """Resolve the on-disk ``.prompt.md`` path, preferring variant over base."""
    if style is not None:
        variant = _TEMPLATE_DIR / f"{call_type}.{style}.prompt.md"
        if variant.exists():
            return variant
    return _TEMPLATE_DIR / f"{call_type}.prompt.md"


def _compute_prompt_version(path: Path) -> str:
    """Return SHA-256[:8] of *path*'s bytes, cached by (path, mtime_ns).

    Returns ``"unknown"`` when the file is missing or unreadable. The cache
    keys on ``stat().st_mtime_ns`` so any on-disk edit invalidates the entry
    on next access, while repeated reads of an unchanged template skip disk.
    """
    try:
        stat = path.stat()
    except OSError:
        return _UNKNOWN_VERSION
    cache_key = (str(path), stat.st_mtime_ns)
    cached = _VERSION_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = path.read_bytes()
    except OSError:
        return _UNKNOWN_VERSION
    version = hashlib.sha256(data).hexdigest()[:8]
    _VERSION_CACHE[cache_key] = version
    return version


class PromptBuilder:
    """Unified prompt assembly with built-in token truncation.

    Loads a template by call_type from the prompts/ directory and supports
    fluent method chaining for adding content, schema, and context variables.
    """

    def __init__(
        self,
        call_type: str,
        model: str | None = None,
        *,
        prompt_style: str | None = None,
    ) -> None:
        """Load template for call_type from prompts/ directory.

        Args:
            call_type: Template name (without extension).
            model: Model identifier for token counting. Defaults to gpt-4o-mini.
            prompt_style: Optional variant style (e.g. ``"structured"``,
                ``"concise"``). When provided, tries
                ``{call_type}.{prompt_style}.prompt.md`` first and falls back to
                ``{call_type}.prompt.md`` when the variant is absent.

        Raises:
            FileNotFoundError: If the base template file does not exist.
        """
        self._template: str = read_prompt_source(call_type, prompt_style)
        self._call_type: str = call_type
        self._prompt_style: str | None = prompt_style
        self._template_path: Path = _resolve_template_path(call_type, prompt_style)
        self._model: str = model if model is not None else _DEFAULT_MODEL
        self._context: dict[str, str] = {}

    @property
    def call_type(self) -> str:
        """The call_type identifier this builder was constructed with."""
        return self._call_type

    @property
    def prompt_version(self) -> str:
        """SHA-256 first 8 hex chars of the template file content.

        Cached by ``(path, mtime_ns)`` — repeated reads of an unchanged
        template skip disk and re-hashing. Returns ``"unknown"`` when the
        template file is missing or unreadable at the time of access.
        """
        return _compute_prompt_version(self._template_path)

    def add_context(self, key: str, value: str) -> PromptBuilder:
        """Add arbitrary context variable for template substitution.

        Args:
            key: Template variable name.
            value: Value to substitute.

        Returns:
            self for method chaining.
        """
        self._context[key] = value
        return self

    def build(self) -> str:
        """Build the final prompt string with all substitutions applied.

        Renders through the same Jinja engine as :func:`load_prompt`, so the
        builder and the free function produce identical output for identical
        inputs.

        Returns:
            The rendered prompt string.
        """
        return load_prompt(self._call_type, style=self._prompt_style, **self._context)

    @staticmethod
    def truncate_content(text: str, max_tokens: int, model: str = "gpt-4o-mini") -> str:
        """Truncate text to fit within token limit, preserving start and end.

        Strategy: keep first 40% + last 10%, replace middle with
        '[...已截断 N 字符...]'.

        Args:
            text: Input text to potentially truncate.
            max_tokens: Maximum allowed token count.
            model: Model identifier for tokenizer selection.

        Returns:
            Original text if under limit, otherwise truncated text.
        """

        def _count(s: str) -> int:
            try:
                c = litellm.token_counter(model=model, text=s)
                return int(c) if isinstance(c, int) else len(s) // 4
            except Exception:
                return len(s) // 4

        if _count(text) <= max_tokens:
            return text

        # SR-007: iteratively shrink character window until the resulting
        # string (including the marker) is actually under the token limit.
        # CJK-dense text has a character:token ratio close to 1:1, so the
        # initial 40%+10% cut is not always sufficient.
        total_len = len(text)
        start_ratio = 0.4
        end_ratio = 0.1

        # Shrink loop: at most 8 iterations (each halving the window).
        for _ in range(8):
            start_len = int(total_len * start_ratio)
            end_len = int(total_len * end_ratio)
            truncated_chars = total_len - start_len - end_len
            start_part = text[:start_len]
            end_part = text[total_len - end_len :] if end_len > 0 else ""
            marker = f"[...已截断 {truncated_chars} 字符...]"
            candidate = start_part + marker + end_part
            if _count(candidate) <= max_tokens:
                return candidate
            start_ratio /= 2
            end_ratio /= 2

        # Final safety fallback: hard char slice (avoid unbounded loop).
        return text[: max(1, max_tokens * 2)] + "[...已截断...]"
