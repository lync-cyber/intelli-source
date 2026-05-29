"""B-047: sync /search/chat sources extraction + answer shaping.

Backlog: docs/BACKLOG-intellisource-v1.md §B-047.

Two real-stack defects:
- #23: extract_answer returned ``str(dict)`` of a get_content_detail step,
  because the step output has a top-level ``content`` key whose value is the
  ProcessedContentDTO dict — the old ``if value:`` matched the dict and
  stringified it, producing answers like ``{'id': ..., 'title': ...}``.
- #22: _extract_sources only harvested ``tool == 'search'`` steps, so when the
  agent loop reached content via get_content_detail (LLM path is
  non-deterministic) the sync response carried zero sources while the stream
  path surfaced them.
"""

from __future__ import annotations

from intellisource.agent.response_utils import extract_answer
from intellisource.api.routers.search import _extract_sources


class TestExtractAnswerNeverReturnsDictRepr:
    def test_get_content_detail_summary_used_not_dict_repr(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "search",
                    "output": {"response": {"items": [{"content_id": "a"}]}},
                },
                {
                    "tool": "get_content_detail",
                    "output": {
                        "status": "ok",
                        "tool": "get_content_detail",
                        "content": {
                            "id": "d90d9026",
                            "title": "Eagle 3.1",
                            "body_text": "full body text",
                            "summary": "Eagle 3.1 是一篇关于推测解码的论文。",
                        },
                        "content_id": "d90d9026",
                    },
                },
            ]
        }

        answer = extract_answer(flex_result)

        assert answer == "Eagle 3.1 是一篇关于推测解码的论文。"
        assert "{" not in answer and "'id'" not in answer

    def test_falls_back_to_body_text_when_no_summary(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "get_content_detail",
                    "output": {
                        "content": {
                            "id": "x",
                            "title": "T",
                            "body_text": "body fallback answer",
                            "summary": "",
                        },
                    },
                },
            ]
        }

        answer = extract_answer(flex_result)

        assert answer == "body fallback answer"

    def test_dict_valued_top_level_content_never_stringified(self) -> None:
        # A step whose output has content as a dict but with no usable text
        flex_result = {
            "results": [
                {
                    "tool": "get_content_detail",
                    "output": {"content": {"id": "x", "tags": ["a"]}},
                },
            ]
        }

        answer = extract_answer(flex_result)

        assert answer == ""
        assert "{" not in answer

    def test_final_answer_still_preferred(self) -> None:
        flex_result = {
            "final_answer": "natural language answer",
            "results": [
                {"tool": "get_content_detail", "output": {"content": {"id": "x"}}},
            ],
        }

        assert extract_answer(flex_result) == "natural language answer"


class TestExtractSourcesFromContentDetail:
    def test_sources_harvested_from_get_content_detail(self) -> None:
        flex_result = {
            "results": [
                {
                    "tool": "get_content_detail",
                    "output": {
                        "content": {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "title": "RAG Survey",
                            "source_url": "https://example.com/rag",
                        },
                    },
                },
            ]
        }

        sources = _extract_sources(flex_result)

        assert len(sources) == 1
        assert sources[0].title == "RAG Survey"
        assert str(sources[0].content_id) == "11111111-1111-1111-1111-111111111111"
        assert sources[0].url == "https://example.com/rag"

    def test_sources_deduped_across_search_and_detail(self) -> None:
        cid = "22222222-2222-2222-2222-222222222222"
        flex_result = {
            "results": [
                {
                    "tool": "search",
                    "output": {
                        "response": {"items": [{"content_id": cid, "title": "Paper"}]}
                    },
                },
                {
                    "tool": "get_content_detail",
                    "output": {"content": {"id": cid, "title": "Paper"}},
                },
            ]
        }

        sources = _extract_sources(flex_result)

        assert len(sources) == 1
        assert str(sources[0].content_id) == cid

    def test_search_only_path_still_works(self) -> None:
        cid = "33333333-3333-3333-3333-333333333333"
        flex_result = {
            "results": [
                {
                    "tool": "search",
                    "output": {
                        "response": {
                            "items": [{"title": "RAG Survey", "content_id": cid}]
                        }
                    },
                }
            ]
        }

        sources = _extract_sources(flex_result)

        assert len(sources) == 1
        assert sources[0].title == "RAG Survey"
