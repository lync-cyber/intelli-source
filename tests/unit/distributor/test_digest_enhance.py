"""WF-5.4: DigestEnhancer — optional LLM enrichment (intro + why_it_matters)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from intellisource.distributor.digest_enhance import DigestEnhancer
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


class _StubLLM:
    """Returns ``ENH:<task_type>`` as content; records the task_types called."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self._fail_on = fail_on or set()
        self.task_types: list[str] = []

    async def complete(self, *, prompt: str, task_type: str, **_kw: Any) -> Any:
        self.task_types.append(task_type)
        if task_type in self._fail_on:
            raise RuntimeError("llm boom")
        return SimpleNamespace(content=f"ENH:{task_type}")


def _bundle() -> DigestBundle:
    return DigestBundle(
        title="每日速览",
        top_picks=[DigestItem(title="头条")],
        sections=[DigestSection(heading="AI", items=[DigestItem(title="次条")])],
    )


class TestEnhance:
    async def test_fills_intro_and_per_item_why(self) -> None:
        bundle = _bundle()
        llm = _StubLLM()
        await DigestEnhancer(llm).enhance(bundle)

        assert bundle.intro == "ENH:digest_intro"
        assert bundle.top_picks[0].why_it_matters == "ENH:digest_why"
        assert bundle.sections[0].items[0].why_it_matters == "ENH:digest_why"
        # one intro call + one why call per item (2 items)
        assert llm.task_types.count("digest_intro") == 1
        assert llm.task_types.count("digest_why") == 2

    async def test_degrades_when_all_calls_fail(self) -> None:
        bundle = _bundle()
        llm = _StubLLM(fail_on={"digest_intro", "digest_why"})
        await DigestEnhancer(llm).enhance(bundle)

        # No exception; fields stay unset rather than corrupting the digest.
        assert bundle.intro is None
        assert bundle.top_picks[0].why_it_matters is None
        assert bundle.sections[0].items[0].why_it_matters is None

    async def test_per_item_degrade_is_independent_of_intro(self) -> None:
        bundle = _bundle()
        llm = _StubLLM(fail_on={"digest_why"})
        await DigestEnhancer(llm).enhance(bundle)

        assert bundle.intro == "ENH:digest_intro"
        assert bundle.top_picks[0].why_it_matters is None

    async def test_blank_llm_output_leaves_field_unset(self) -> None:
        class _BlankLLM:
            async def complete(self, *, prompt: str, task_type: str, **_kw: Any) -> Any:
                return SimpleNamespace(content="   ")

        bundle = _bundle()
        await DigestEnhancer(_BlankLLM()).enhance(bundle)
        assert bundle.intro is None
        assert bundle.top_picks[0].why_it_matters is None
