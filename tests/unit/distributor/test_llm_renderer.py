"""WF-6.2/6.4: LLMRenderer — guardrails, code fallback, cache, budget."""

from __future__ import annotations

from typing import Any

from intellisource.distributor.llm_renderer import LLMRenderer
from intellisource.distributor.templates.renderers import Renderer
from intellisource.distributor.templates.schemas import (
    DigestBundle,
    DigestItem,
    DigestSection,
)


def _bundle() -> DigestBundle:
    return DigestBundle(
        title="今日 AI 速览",
        top_picks=[DigestItem(title="大模型新突破", summary="性能翻倍")],
        sections=[
            DigestSection(
                heading="安全",
                items=[DigestItem(title="新型漏洞披露", summary="影响广泛")],
            )
        ],
    )


class _StubLLM:
    """A stub gateway whose complete() returns a fixed body (or raises)."""

    def __init__(self, *, content: str = "", raises: bool = False) -> None:
        self._content = content
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, prompt: str, **kwargs: Any) -> Any:
        self.calls.append({"prompt": prompt, **kwargs})
        if self._raises:
            raise RuntimeError("llm down")
        return type("R", (), {"content": self._content})()


class _CodeRenderer:
    """A stub fallback renderer returning a recognizable marker."""

    async def render(self, **kwargs: Any) -> str:
        return "CODE-FALLBACK-BODY"


def _renderer(llm: _StubLLM, **kw: Any) -> LLMRenderer:
    fallback: Renderer = _CodeRenderer()  # type: ignore[assignment]
    return LLMRenderer(llm, fallback=fallback, **kw)


class TestSuccessfulRender:
    async def test_returns_llm_body_when_valid(self) -> None:
        llm = _StubLLM(content="## 今日 AI 速览\n- 大模型新突破：性能翻倍")
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert out == "## 今日 AI 速览\n- 大模型新突破：性能翻倍"

    async def test_prompt_includes_item_titles(self) -> None:
        llm = _StubLLM(content="今日 AI 速览\n大模型新突破")
        await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        prompt = llm.calls[0]["prompt"]
        assert "大模型新突破" in prompt
        assert "新型漏洞披露" in prompt


class TestHtmlSanitisation:
    async def test_strips_script_tags(self) -> None:
        llm = _StubLLM(
            content="<p>今日 AI 速览 大模型新突破</p><script>alert(1)</script>"
        )
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="html", bundle=_bundle(), config={}
        )
        assert "<script>" not in out
        assert "alert(1)" not in out
        assert "<p>" in out

    async def test_keeps_safe_anchor(self) -> None:
        llm = _StubLLM(
            content='<p>今日 AI 速览</p><a href="https://x.io">大模型新突破</a>'
        )
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="html", bundle=_bundle(), config={}
        )
        assert 'href="https://x.io"' in out


class TestFallbackToCode:
    async def test_llm_exception_falls_back(self) -> None:
        llm = _StubLLM(raises=True)
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert out == "CODE-FALLBACK-BODY"

    async def test_empty_output_falls_back(self) -> None:
        llm = _StubLLM(content="   ")
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert out == "CODE-FALLBACK-BODY"

    async def test_unfaithful_refusal_falls_back(self) -> None:
        """An LLM refusal that mentions none of the items degrades to code."""
        llm = _StubLLM(content="对不起，我无法完成这个请求。")
        out = await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert out == "CODE-FALLBACK-BODY"

    async def test_sensitive_words_fall_back(self) -> None:
        class _Filter:
            def filter_output(self, text: str) -> tuple[str, list[str]]:
                return text, ["敏感词"] if "大模型新突破" in text else []

        llm = _StubLLM(content="大模型新突破 详情")
        out = await _renderer(llm, content_filter=_Filter()).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert out == "CODE-FALLBACK-BODY"


class TestCacheAndBudget:
    async def test_passes_cache_key_parts(self) -> None:
        llm = _StubLLM(content="今日 AI 速览 大模型新突破")
        await _renderer(llm).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        parts = llm.calls[0]["cache_key_parts"]
        assert parts["call_type"] == "render"
        assert parts["content_fingerprint"]
        assert "prompt_version" in parts

    async def test_cache_disabled_omits_cache_key_parts(self) -> None:
        llm = _StubLLM(content="今日 AI 速览 大模型新突破")
        await _renderer(llm, cache_enabled=False).render(
            template_name="daily-brief", fmt="markdown", bundle=_bundle(), config={}
        )
        assert llm.calls[0].get("cache_key_parts") is None

    async def test_budget_truncates_items_block(self) -> None:
        big = DigestBundle(
            title="今日 AI 速览",
            top_picks=[
                DigestItem(title=f"条目{i}", summary="x" * 200) for i in range(50)
            ],
        )
        llm = _StubLLM(content="今日 AI 速览 条目0")
        await _renderer(llm, budget_chars=300).render(
            template_name="daily-brief", fmt="markdown", bundle=big, config={}
        )
        prompt = llm.calls[0]["prompt"]
        assert "truncated" in prompt
