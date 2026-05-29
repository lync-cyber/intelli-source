"""Tests for ChatSearchRequest / ChatSearchResponse Pydantic schemas (AC-2).

Verifies field types, required vs optional fields, and serialization shape
of the new schemas that replace the old ChatRequest in the /search/chat route.
"""

from __future__ import annotations

import pytest


class TestChatSearchRequest:
    """AC-2: ChatSearchRequest schema field validation."""

    def test_import_chat_search_request(self) -> None:
        """ChatSearchRequest must be importable from api.schemas.search."""
        from pydantic import BaseModel

        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        assert issubclass(ChatSearchRequest, BaseModel)

    def test_message_is_required(self) -> None:
        """message field is required; omitting it raises ValidationError."""
        from pydantic import ValidationError

        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        with pytest.raises(ValidationError):
            ChatSearchRequest()

    def test_message_field_type_str(self) -> None:
        """message field accepts a string value."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="找最近的 RAG 论文")
        assert req.message == "找最近的 RAG 论文"

    def test_session_id_optional(self) -> None:
        """session_id is optional and defaults to None."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="hello")
        assert req.session_id is None

    def test_session_id_accepts_string(self) -> None:
        """session_id accepts a string when provided."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="hello", session_id="sess-abc")
        assert req.session_id == "sess-abc"

    def test_max_tokens_budget_optional(self) -> None:
        """max_tokens_budget is optional and defaults to None."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="hello")
        assert req.max_tokens_budget is None

    def test_max_tokens_budget_accepts_int(self) -> None:
        """max_tokens_budget accepts an integer."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="hello", max_tokens_budget=4096)
        assert req.max_tokens_budget == 4096

    def test_session_optional_dict(self) -> None:
        """session field is optional and defaults to empty dict or None."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        req = ChatSearchRequest(message="hello")
        # session can be None or {} — both are valid defaults
        assert req.session is None or req.session == {}

    def test_session_accepts_dict(self) -> None:
        """session field accepts a dict payload."""
        from intellisource.api.schemas.search import (
            ChatSearchRequest,
        )

        session_data = {"user": "u-1", "context": "prior topic"}
        req = ChatSearchRequest(message="hello", session=session_data)
        assert req.session == session_data


class TestChatSource:
    """AC-2: ChatSource sub-model for source references in response."""

    def test_import_chat_source(self) -> None:
        """ChatSource must be importable from api.schemas.search."""
        from pydantic import BaseModel

        from intellisource.api.schemas.search import ChatSource

        assert issubclass(ChatSource, BaseModel)

    def test_chat_source_has_required_fields(self) -> None:
        """ChatSource should contain at minimum title and url or content_id."""
        from intellisource.api.schemas.search import ChatSource

        # Instantiate with expected fields — exact required set drives GREEN
        source = ChatSource(title="RAG Survey 2024", url="https://arxiv.org/abs/123")
        assert source.title == "RAG Survey 2024"


class TestChatSearchResponse:
    """AC-2: ChatSearchResponse schema serialization with 5 fields."""

    def test_import_chat_search_response(self) -> None:
        """ChatSearchResponse must be importable from api.schemas.search."""
        from pydantic import BaseModel

        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        assert issubclass(ChatSearchResponse, BaseModel)

    def test_response_has_session_id(self) -> None:
        """ChatSearchResponse contains session_id field."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-1",
            answer="Here is the summary.",
            sources=[],
            query_time_ms=42,
            steps_executed=2,
            task_chain_id="tc-abc",
        )
        assert resp.session_id == "sess-1"

    def test_response_has_answer(self) -> None:
        """ChatSearchResponse contains answer field."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-1",
            answer="Here is the summary.",
            sources=[],
            query_time_ms=42,
            steps_executed=2,
            task_chain_id="tc-abc",
        )
        assert resp.answer == "Here is the summary."

    def test_response_has_sources_list(self) -> None:
        """ChatSearchResponse.sources is a list."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-1",
            answer="result",
            sources=[],
            query_time_ms=11,
            steps_executed=1,
            task_chain_id="tc-xyz",
        )
        assert isinstance(resp.sources, list)

    def test_response_has_steps_executed(self) -> None:
        """ChatSearchResponse contains steps_executed field."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-2",
            answer="done",
            sources=[],
            query_time_ms=12,
            steps_executed=3,
            task_chain_id="tc-def",
        )
        assert resp.steps_executed == 3

    def test_response_has_task_chain_id(self) -> None:
        """ChatSearchResponse contains task_chain_id field."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-3",
            answer="done",
            sources=[],
            query_time_ms=13,
            steps_executed=1,
            task_chain_id="tc-ghi",
        )
        assert resp.task_chain_id == "tc-ghi"

    def test_response_has_query_time_ms(self) -> None:
        """ChatSearchResponse contains query_time_ms field (arch API-013 SLA)."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="sess-q",
            answer="done",
            sources=[],
            query_time_ms=128,
            steps_executed=1,
            task_chain_id="tc-q",
        )
        assert resp.query_time_ms == 128

    def test_response_serializes_six_fields(self) -> None:
        """model_dump() returns a dict containing all six fields."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
        )

        resp = ChatSearchResponse(
            session_id="s",
            answer="a",
            sources=[],
            query_time_ms=14,
            steps_executed=1,
            task_chain_id="t",
        )
        dumped = resp.model_dump()
        required_keys = {
            "session_id",
            "answer",
            "sources",
            "query_time_ms",
            "steps_executed",
            "task_chain_id",
        }
        assert required_keys.issubset(dumped.keys())

    def test_sources_contains_chat_source_instances(self) -> None:
        """sources list accepts ChatSource objects."""
        from intellisource.api.schemas.search import (
            ChatSearchResponse,
            ChatSource,
        )

        source = ChatSource(title="Paper A", url="https://example.com/a")
        resp = ChatSearchResponse(
            session_id="sess-4",
            answer="summary",
            sources=[source],
            query_time_ms=15,
            steps_executed=2,
            task_chain_id="tc-jkl",
        )
        assert len(resp.sources) == 1
        assert resp.sources[0].title == "Paper A"
