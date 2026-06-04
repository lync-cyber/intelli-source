"""LLMRenderer — the ``llm-freeform`` render mode with guardrails.

Renders a :class:`DigestBundle` body by prompting the LLM (``render.{fmt}.prompt.md``)
instead of the packaged Jinja template. Every output passes contract validation,
HTML sanitisation (bleach) and a sensitive-word recheck; any failure — guardrail
trip, empty output, or LLM error — degrades to the injected code renderer, so the
freeform mode is a zero-risk overlay on the Jinja path.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import bleach  # type: ignore[import-untyped]

from intellisource.distributor.templates.renderers import JinjaRenderer, Renderer
from intellisource.distributor.templates.schemas import DigestBundle, DigestItem
from intellisource.llm.prompts import load_prompt
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)

_METRIC_RENDER_TOTAL = "digest_render_total"
_RENDER_STYLES = frozenset({"html", "markdown", "text"})
_DEFAULT_BUDGET_CHARS = 6000

# Email-safe HTML subset kept after sanitising free-form LLM output.
_ALLOWED_TAGS = [
    "h1",
    "h2",
    "h3",
    "p",
    "ul",
    "ol",
    "li",
    "a",
    "strong",
    "em",
    "b",
    "i",
    "br",
    "blockquote",
    "code",
    "pre",
    "hr",
]
_ALLOWED_ATTRS = {"a": ["href", "title"]}

# Tags whose inner content (not just the tag) must be dropped before bleach,
# which by default keeps the text of stripped tags (e.g. <script>alert(1)</script>
# would otherwise leave a stray "alert(1)").
_DANGEROUS_BLOCK = re.compile(r"(?is)<(script|style|iframe)\b.*?</\1\s*>")


class RenderGuardError(Exception):
    """Raised when an LLM-rendered body fails a guardrail (→ code fallback)."""


class LLMRenderer:
    """``llm-freeform`` renderer: prompt the LLM, guard output, fall back to code."""

    def __init__(
        self,
        llm_gateway: Any,
        *,
        fallback: Renderer | None = None,
        content_filter: Any = None,
        cache_enabled: bool = True,
        budget_chars: int = _DEFAULT_BUDGET_CHARS,
    ) -> None:
        self._llm = llm_gateway
        self._fallback: Renderer = fallback or JinjaRenderer()
        self._filter = content_filter
        self._cache_enabled = cache_enabled
        self._budget_chars = budget_chars

    async def render(
        self,
        *,
        template_name: str,
        fmt: str,
        bundle: DigestBundle,
        config: dict[str, Any],
    ) -> str:
        """Render *bundle* via the LLM, degrading to code on any failure."""
        try:
            body = await self._llm_render(fmt, bundle, config)
        except Exception as exc:  # noqa: BLE001 — any failure degrades to code
            _logger.warning("llm render fmt=%s degraded to code: %s", fmt, exc)
            self._record(fmt, "fallback")
            return await self._fallback.render(
                template_name=template_name, fmt=fmt, bundle=bundle, config=config
            )
        self._record(fmt, "llm")
        return body

    async def _llm_render(
        self, fmt: str, bundle: DigestBundle, config: dict[str, Any]
    ) -> str:
        style = fmt if fmt in _RENDER_STYLES else "markdown"
        items = self._serialize_items(bundle, config)
        prompt = load_prompt("render", style=style, title=bundle.title, items=items)
        cache_parts: dict[str, str] | None = None
        if self._cache_enabled:
            cache_parts = {
                "content_fingerprint": hashlib.sha256(
                    prompt.encode("utf-8")
                ).hexdigest(),
                "call_type": "render",
                "prompt_version": f"render-{style}",
            }
        result = await self._llm.complete(
            prompt=prompt, task_type="render", cache_key_parts=cache_parts
        )
        draft = str(getattr(result, "content", "") or "").strip()
        return self._guard(draft, fmt, bundle)

    def _serialize_items(self, bundle: DigestBundle, config: dict[str, Any]) -> str:
        """Flatten the bundle into a compact, budget-capped item block."""
        lines: list[str] = []
        if bundle.intro:
            lines.append(bundle.intro)
        for item in self._all_items(bundle):
            seg = f"- {item.title}"
            detail = item.summary or item.why_it_matters or item.body_text or ""
            if detail:
                seg += f": {detail}"
            if item.source_url:
                seg += f" ({item.source_url})"
            lines.append(seg)
        text = "\n".join(lines)
        budget = int(config.get("render_budget_chars", self._budget_chars))
        if budget > 0 and len(text) > budget:
            text = text[:budget] + "\n[...truncated...]"
        return text

    def _guard(self, draft: str, fmt: str, bundle: DigestBundle) -> str:
        """Validate + sanitise the LLM body, raising RenderGuardError to fall back."""
        if not draft:
            raise RenderGuardError("empty llm render")
        if fmt == "html":
            draft = _DANGEROUS_BLOCK.sub("", draft)
            draft = bleach.clean(
                draft,
                tags=_ALLOWED_TAGS,
                attributes=_ALLOWED_ATTRS,
                strip=True,
            ).strip()
            if not draft:
                raise RenderGuardError("html empty after sanitise")
        if not self._is_faithful(draft, bundle):
            raise RenderGuardError("llm render mentions none of the digest items")
        if self._filter is not None:
            _, matched = self._filter.filter_output(draft)
            if matched:
                raise RenderGuardError(f"sensitive words in llm render: {matched}")
        return draft

    def _is_faithful(self, draft: str, bundle: DigestBundle) -> bool:
        """True when the body references the digest — its title or any item title.

        Guards against refusals / hallucinated-empty output sneaking past the
        non-empty check. A render task should preserve the source titles.
        """
        candidates = [bundle.title, *(i.title for i in self._all_items(bundle))]
        meaningful = [c for c in candidates if c and len(c) >= 2]
        if not meaningful:
            return True
        return any(c in draft for c in meaningful)

    def _record(self, fmt: str, outcome: str) -> None:
        """Bump digest_render_total{fmt, outcome}; metric failures never abort."""
        try:
            from intellisource.observability.metrics import MetricsCollector

            mc = MetricsCollector.get_instance()
            mc.register_labeled_counter(
                _METRIC_RENDER_TOTAL,
                labelnames=["fmt", "outcome"],
                description="Digest LLM render outcomes by format",
            )
            mc.increment_labeled_counter(
                _METRIC_RENDER_TOTAL, labels={"fmt": fmt, "outcome": outcome}
            )
        except Exception:  # noqa: BLE001 — metrics must not break rendering
            _logger.debug("digest render metric skipped", exc_info=True)

    @staticmethod
    def _all_items(bundle: DigestBundle) -> list[DigestItem]:
        items = list(bundle.top_picks)
        for section in bundle.sections:
            items.extend(section.items)
        return items


__all__ = ["LLMRenderer", "RenderGuardError"]
