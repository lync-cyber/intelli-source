"""Tests for the `init` topic-materialization helpers (host-side source files)."""

from __future__ import annotations

from pathlib import Path

from intellisource.cli.main import (
    _materialize_topic_sources,
    _select_topics,
)
from intellisource.config.validator import ConfigValidator
from intellisource.topic.loader import TopicLoader


class TestSelectTopics:
    def test_arg_resolves_ids_in_order(self) -> None:
        chosen = _select_topics("finance,technology", non_interactive=True)
        assert [t.id for t in chosen] == ["finance", "technology"]

    def test_arg_resolves_numeric_index(self) -> None:
        all_ids = [t.id for t in TopicLoader().load_all()]
        chosen = _select_topics("1", non_interactive=True)
        assert chosen[0].id == all_ids[0]

    def test_unknown_id_is_skipped(self) -> None:
        chosen = _select_topics("finance,nope", non_interactive=True)
        assert [t.id for t in chosen] == ["finance"]

    def test_duplicates_deduped(self) -> None:
        chosen = _select_topics("finance,finance", non_interactive=True)
        assert [t.id for t in chosen] == ["finance"]

    def test_none_arg_non_interactive_returns_empty(self) -> None:
        assert _select_topics(None, non_interactive=True) == []

    def test_blank_arg_returns_empty(self) -> None:
        assert _select_topics("", non_interactive=True) == []


class TestMaterializeTopicSources:
    def test_writes_parseable_sources_file(self, tmp_path: Path) -> None:
        topic = TopicLoader().load_by_id("technology")
        assert topic is not None
        path = _materialize_topic_sources(topic, tmp_path)
        assert path == tmp_path / "topic-technology.yaml"

        cfgs = ConfigValidator().validate_sources_file(
            path.read_text(encoding="utf-8"), format="yaml"
        )
        assert len(cfgs) == len(topic.sources)
        assert {c.name for c in cfgs} == {s.name for s in topic.sources}

    def test_discipline_topic_file_carries_discipline_tags(
        self, tmp_path: Path
    ) -> None:
        topic = TopicLoader().load_by_id("electrical-engineering")
        assert topic is not None
        path = _materialize_topic_sources(topic, tmp_path)
        cfgs = ConfigValidator().validate_sources_file(
            path.read_text(encoding="utf-8"), format="yaml"
        )
        for cfg in cfgs:
            assert "电气工程" in cfg.discipline_tags

    def test_creates_missing_directory(self, tmp_path: Path) -> None:
        topic = TopicLoader().load_by_id("finance")
        assert topic is not None
        nested = tmp_path / "config" / "sources"
        path = _materialize_topic_sources(topic, nested)
        assert path.exists()
        assert path.parent == nested
