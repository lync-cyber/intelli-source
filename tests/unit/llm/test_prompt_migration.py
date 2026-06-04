"""WF-4.2/4.3: every prompt is a single-format ``.prompt.md`` with fragments.

Encodes the end state of the format consolidation:
- no ``.txt`` template survives in the prompts package,
- every known prompt loads as ``.prompt.md`` and renders without leaking
  Jinja delimiters,
- the reusable ``_fragments/`` (editor persona + injection guard) exist and
  are actually included by their consumers,
- the legacy ``format_map`` / ``_read_template`` path is gone.
"""

from __future__ import annotations

import pytest

from intellisource.llm.prompts import load_prompt
from intellisource.llm.prompts.loader import _TEMPLATE_DIR

# (name, style, render kwargs) for every shipped prompt.
PROMPTS: list[tuple[str, str | None, dict[str, str]]] = [
    ("cluster", None, {"title": "T", "body_text": "B"}),
    ("compaction_summary", None, {"conversation_history": "user: hi"}),
    ("context_compress", None, {"conversation": "user: hi"}),
    ("dedup", None, {"title": "T", "body_text": "B", "candidate_info": "C"}),
    ("extraction", None, {"schema": '{"type":"object"}', "body_text": "B"}),
    ("extraction", "concise", {"schema": '{"type":"object"}', "body_text": "B"}),
    ("extraction", "structured", {"schema": '{"type":"object"}', "body_text": "B"}),
    ("optimizer", None, {"channel": "email", "title": "T", "body_text": "B"}),
    ("summarizer", None, {"docs_text": "D"}),
    ("summarizer", "structured", {"docs_text": "D"}),
    ("tagger", None, {"title": "T", "body_text": "B", "library_hint": ""}),
    ("digest_intro", None, {"title": "T", "items": "- a"}),
    ("digest_why", None, {"title": "T", "summary": "S"}),
    ("render", "html", {"title": "T", "items": "- a"}),
    ("render", "markdown", {"title": "T", "items": "- a"}),
    ("render", "text", {"title": "T", "items": "- a"}),
]


def test_no_txt_template_survives() -> None:
    """4.3: the dual-format ``.txt`` path is fully removed from the package."""
    leftover = sorted(p.name for p in _TEMPLATE_DIR.glob("*.txt"))
    assert leftover == []


def test_loader_has_no_format_map_path() -> None:
    """4.3: loader no longer exposes the legacy ``_read_template`` shim."""
    import intellisource.llm.prompts.loader as loader_mod

    assert not hasattr(loader_mod, "_read_template")


@pytest.mark.parametrize("name,style,kwargs", PROMPTS, ids=lambda v: str(v))
def test_every_prompt_is_prompt_md(
    name: str, style: str | None, kwargs: dict[str, str]
) -> None:
    """4.2: each shipped prompt exists as a ``.prompt.md`` file."""
    fname = f"{name}.{style}.prompt.md" if style else f"{name}.prompt.md"
    assert (_TEMPLATE_DIR / fname).exists(), f"missing {fname}"


@pytest.mark.parametrize("name,style,kwargs", PROMPTS, ids=lambda v: str(v))
def test_every_prompt_renders_without_delimiter_leak(
    name: str, style: str | None, kwargs: dict[str, str]
) -> None:
    """4.2: rendered output substitutes all vars — no raw Jinja delimiters."""
    out = load_prompt(name, style=style, **kwargs)
    assert out.strip()
    for token in ("{{", "}}", "{%", "%}"):
        assert token not in out, f"{name}/{style} leaked {token!r}"


class TestFragments:
    """4.2: reusable fragments exist and are genuinely included."""

    def test_fragment_files_exist(self) -> None:
        frag = _TEMPLATE_DIR / "_fragments"
        assert (frag / "editor_persona.md").exists()
        assert (frag / "injection_guard.md").exists()

    def test_persona_fragment_reused_by_digests(self) -> None:
        """digest_intro and digest_why both include the persona fragment."""
        intro = (_TEMPLATE_DIR / "digest_intro.prompt.md").read_text(encoding="utf-8")
        why = (_TEMPLATE_DIR / "digest_why.prompt.md").read_text(encoding="utf-8")
        assert "editor_persona.md" in intro
        assert "editor_persona.md" in why

    def test_persona_text_renders_into_digest(self) -> None:
        """The shared persona text reaches the rendered digest prompt."""
        persona = (_TEMPLATE_DIR / "_fragments" / "editor_persona.md").read_text(
            encoding="utf-8"
        )
        marker = persona.strip().split("\n", 1)[0][:8]
        out = load_prompt("digest_intro", title="T", items="- a")
        assert marker in out

    def test_injection_guard_used_by_a_content_prompt(self) -> None:
        """At least one external-content prompt imports the injection guard."""
        dedup = (_TEMPLATE_DIR / "dedup.prompt.md").read_text(encoding="utf-8")
        assert "injection_guard.md" in dedup

    def test_injection_guard_defense_text_renders(self) -> None:
        """The guard's defense sentence reaches the rendered prompt body."""
        out = load_prompt("dedup", title="T", body_text="B", candidate_info="C")
        assert "untrusted" in out.lower() or "ignore any instructions" in out.lower()
