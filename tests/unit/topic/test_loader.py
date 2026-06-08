"""Tests for the built-in topic catalog loader and Topic model conversions."""

from __future__ import annotations

from pathlib import Path

from intellisource.config.models import SourceConfig
from intellisource.config.subscription_models import SubscriptionConfig
from intellisource.config.subscription_validator import SubscriptionValidator
from intellisource.config.validator import ConfigValidator
from intellisource.topic.loader import TopicLoader
from intellisource.topic.models import Topic, TopicSource, TopicSubscriptionTemplate

_EXPECTED_IDS = {
    "electrical-engineering",
    "computer-science",
    "biomedicine",
    "artificial-intelligence",
    "finance",
    "technology",
}


class TestBuiltinCatalog:
    def test_loads_all_six_builtin_topics(self) -> None:
        topics = TopicLoader().load_all()
        assert {t.id for t in topics} == _EXPECTED_IDS

    def test_topic_ids_are_unique(self) -> None:
        topics = TopicLoader().load_all()
        ids = [t.id for t in topics]
        assert len(ids) == len(set(ids))

    def test_covers_both_discipline_and_industry_axes(self) -> None:
        dims = {t.dimension for t in TopicLoader().load_all()}
        assert "discipline" in dims
        assert "industry" in dims

    def test_every_topic_has_at_least_one_source(self) -> None:
        for t in TopicLoader().load_all():
            assert len(t.sources) >= 1, f"{t.id} has no sources"

    def test_builtin_source_configs_pass_semantic_validation(self) -> None:
        validator = ConfigValidator()
        for t in TopicLoader().load_all():
            for cfg in t.source_configs():
                assert isinstance(cfg, SourceConfig)
                # raises ConfigValidationError on bad name/type/url
                validator.validate(cfg)

    def test_discipline_topics_propagate_discipline_tags_to_sources(self) -> None:
        topics = {t.id: t for t in TopicLoader().load_all()}
        ee = topics["electrical-engineering"]
        assert ee.dimension == "discipline"
        for src in ee.sources:
            assert "电气工程" in src.discipline_tags

    def test_builtin_subscription_templates_validate_for_wework(self) -> None:
        validator = SubscriptionValidator()
        for t in TopicLoader().load_all():
            sub = t.build_subscription(channel="wework", channel_config={})
            assert isinstance(sub, SubscriptionConfig)
            validator.validate(sub)


class TestLoadById:
    def test_load_by_id_returns_matching_topic(self) -> None:
        topic = TopicLoader().load_by_id("artificial-intelligence")
        assert topic is not None
        assert topic.name == "人工智能"
        assert topic.dimension == "industry"

    def test_load_by_id_unknown_returns_none(self) -> None:
        assert TopicLoader().load_by_id("does-not-exist") is None


class TestBuildSubscription:
    def _topic(self) -> Topic:
        return Topic(
            id="t1",
            name="测试主题",
            dimension="discipline",
            discipline_tags=["电气工程"],
            subscription_template=TopicSubscriptionTemplate(
                name="自定义订阅名",
                match_rules={"discipline_tags": ["电气工程"]},
                frequency="daily",
                discipline_tags=["电气工程"],
            ),
        )

    def test_uses_template_name_and_rules(self) -> None:
        sub = self._topic().build_subscription(channel="wework", channel_config={})
        assert sub.name == "自定义订阅名"
        assert sub.match_rules == {"discipline_tags": ["电气工程"]}
        assert sub.discipline_tags == ["电气工程"]
        assert sub.frequency == "daily"

    def test_explicit_name_override_wins(self) -> None:
        sub = self._topic().build_subscription(
            channel="email",
            channel_config={"to_addr": "u@example.com"},
            name="覆盖名",
        )
        assert sub.name == "覆盖名"
        assert sub.channel == "email"

    def test_falls_back_to_topic_name_when_template_missing(self) -> None:
        topic = Topic(id="t2", name="裸主题", dimension="general")
        sub = topic.build_subscription(channel="wework", channel_config={})
        assert sub.name == "裸主题 订阅"
        assert sub.match_rules == {}

    def _topic_with_sources(self) -> Topic:
        return Topic(
            id="t3",
            name="带源主题",
            dimension="industry",
            sources=[
                TopicSource(name="源甲", type="rss", url="https://a.example/feed"),
                TopicSource(name="源乙", type="rss", url="https://b.example/feed"),
            ],
            subscription_template=TopicSubscriptionTemplate(
                match_rules={"tags": ["科技"]},
                frequency="daily",
            ),
        )

    def test_injects_source_names_from_pack_sources(self) -> None:
        sub = self._topic_with_sources().build_subscription(
            channel="email", channel_config={"to_addr": "u@example.com"}
        )
        assert sub.match_rules["source_names"] == ["源甲", "源乙"]
        # the template's own rules are preserved alongside the injected names
        assert sub.match_rules["tags"] == ["科技"]

    def test_explicit_source_names_in_template_preserved(self) -> None:
        topic = self._topic_with_sources()
        assert topic.subscription_template is not None
        topic.subscription_template.match_rules = {"source_names": ["仅源甲"]}
        sub = topic.build_subscription(channel="wework", channel_config={})
        assert sub.match_rules["source_names"] == ["仅源甲"]

    def test_no_sources_leaves_match_rules_without_source_names(self) -> None:
        sub = self._topic().build_subscription(channel="wework", channel_config={})
        assert "source_names" not in sub.match_rules


class TestEmptyDir:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        loader = TopicLoader(builtin_dir=tmp_path / "nope")
        assert loader.load_all() == []

    def test_bad_yaml_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "broken.yaml").write_text("id: x\nname: 缺字段\n", encoding="utf-8")
        (tmp_path / "good.yaml").write_text(
            "id: good\nname: 好\ndimension: general\nsources: []\n",
            encoding="utf-8",
        )
        loader = TopicLoader(builtin_dir=tmp_path)
        topics = loader.load_all()
        assert [t.id for t in topics] == ["good"]
