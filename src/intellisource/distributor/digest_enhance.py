"""DigestEnhancer — optional LLM enrichment of a DigestBundle.

Fills the bundle's ``intro`` and each item's ``why_it_matters`` via the LLM
gateway. Every enrichment degrades independently: a failed or empty LLM call
leaves that field unset and never aborts the digest.
"""

from __future__ import annotations

from typing import Any

from intellisource.distributor.templates.schemas import DigestBundle, DigestItem
from intellisource.llm.prompts import load_prompt
from intellisource.observability.logging import get_logger

_logger = get_logger(__name__)


class DigestEnhancer:
    """Fill a bundle's intro + per-item why_it_matters via the LLM gateway."""

    def __init__(self, llm_gateway: Any) -> None:
        self._llm = llm_gateway

    async def enhance(self, bundle: DigestBundle) -> None:
        """Mutate *bundle* in place, best-effort."""
        items = self._all_items(bundle)
        intro = await self._intro(bundle, items)
        if intro:
            bundle.intro = intro
        for item in items:
            why = await self._why(item)
            if why:
                item.why_it_matters = why

    @staticmethod
    def _all_items(bundle: DigestBundle) -> list[DigestItem]:
        items = list(bundle.top_picks)
        for section in bundle.sections:
            items.extend(section.items)
        return items

    async def _intro(self, bundle: DigestBundle, items: list[DigestItem]) -> str | None:
        titles = "\n".join(f"- {item.title}" for item in items[:20])
        prompt = load_prompt("digest_intro", title=bundle.title, items=titles)
        return await self._call(prompt, "digest_intro")

    async def _why(self, item: DigestItem) -> str | None:
        prompt = load_prompt(
            "digest_why",
            title=item.title,
            summary=item.summary or item.body_text or "",
        )
        return await self._call(prompt, "digest_why")

    async def _call(self, prompt: str, task_type: str) -> str | None:
        try:
            result = await self._llm.complete(prompt=prompt, task_type=task_type)
        except Exception:  # noqa: BLE001 — enrichment degrades, never aborts
            _logger.warning("digest enhancement %s failed; degrading", task_type)
            return None
        text = str(getattr(result, "content", "") or "").strip()
        return text or None
