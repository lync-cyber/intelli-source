"""WF-5.2: DigestAssembler — periodic (daily/weekly) digest assembly for one sub."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from intellisource.distributor.digest import DigestAssembler, DigestPayload
from intellisource.distributor.frequency import FrequencyController

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class StubSubscription:
    id: str = "sub-1"
    channel: str = "email"
    channel_config: dict[str, Any] = field(
        default_factory=lambda: {"to_addr": "u@x.io"}
    )
    match_rules: dict[str, Any] = field(default_factory=lambda: {"tags": ["AI"]})
    frequency: str = "daily"
    quiet_hours: dict[str, Any] | None = None
    timezone: str = "UTC"
    last_sent_at: datetime | None = None
    status: str = "active"


@dataclass
class StubContent:
    id: str
    title: str
    body_text: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=lambda: ["AI"])
    discipline_tags: list[str] = field(default_factory=list)
    source_name: str | None = "HN"
    source_url: str | None = None
    published_at: datetime | None = None
    structured_data: dict[str, Any] | None = None


def _assembler() -> DigestAssembler:
    return DigestAssembler(frequency=FrequencyController(clock=_FixedClock()))


class TestNotSent:
    async def test_not_due_returns_none(self) -> None:
        sub = StubSubscription(
            frequency="daily", last_sent_at=NOW - timedelta(minutes=5)
        )
        result = await _assembler().assemble(
            sub, [StubContent(id="c1", title="AI 突破")]
        )
        assert result is None

    async def test_no_matching_content_returns_none(self) -> None:
        sub = StubSubscription(match_rules={"tags": ["AI"]})
        contents = [StubContent(id="c1", title="体育新闻", tags=["sports"])]
        assert await _assembler().assemble(sub, contents) is None

    async def test_quiet_hours_suppresses(self) -> None:
        # 12:00 UTC falls inside 09:00-17:00 quiet window.
        sub = StubSubscription(
            frequency="daily",
            quiet_hours={"start": "09:00", "end": "17:00"},
            last_sent_at=NOW - timedelta(days=2),
        )
        result = await _assembler().assemble(sub, [StubContent(id="c1", title="AI")])
        assert result is None


class TestDailyDigest:
    async def test_daily_digest_renders_brief(self) -> None:
        sub = StubSubscription(channel="email", frequency="daily")
        contents = [
            StubContent(id="c1", title="AI 模型发布", tags=["AI"]),
            StubContent(id="c2", title="新算法突破", tags=["AI"]),
        ]
        result = await _assembler().assemble(sub, contents)
        assert isinstance(result, DigestPayload)
        assert result.channel == "email"
        assert result.fmt == "html"
        assert result.title == "每日速览"
        assert "AI 模型发布" in result.body
        assert result.content_ids == ["c1", "c2"]

    async def test_wework_daily_prefers_markdown(self) -> None:
        sub = StubSubscription(
            channel="wework",
            frequency="daily",
            channel_config={"user_id": "u1"},
        )
        result = await _assembler().assemble(
            sub, [StubContent(id="c1", title="AI 新闻")]
        )
        assert result is not None
        assert result.fmt == "markdown"
        assert "AI 新闻" in result.body

    async def test_dedup_by_content_id(self) -> None:
        sub = StubSubscription(frequency="daily")
        dup = StubContent(id="c1", title="AI 重复")
        result = await _assembler().assemble(sub, [dup, dup])
        assert result is not None
        assert result.content_ids == ["c1"]


class TestWeeklyDigest:
    async def test_weekly_uses_weekly_roundup(self) -> None:
        sub = StubSubscription(channel="email", frequency="weekly")
        contents = [StubContent(id="c1", title="本周要闻", tags=["AI"])]
        result = await _assembler().assemble(sub, contents)
        assert result is not None
        assert result.fmt == "html"
        assert result.title == "每周精选"

    async def test_channel_config_template_override(self) -> None:
        # A weekly sub pinning daily-brief must use daily-brief, not weekly-roundup.
        sub = StubSubscription(
            channel="email",
            frequency="weekly",
            channel_config={"to_addr": "u@x.io", "template": "daily-brief"},
        )
        result = await _assembler().assemble(
            sub, [StubContent(id="c1", title="AI 周报")]
        )
        assert result is not None
        assert result.title == "每日速览"


class _StubEnhancer:
    """Records whether enhance ran; stamps a recognizable intro when it does."""

    def __init__(self) -> None:
        self.called = False

    async def enhance(self, bundle: Any) -> None:
        self.called = True
        bundle.intro = "ENHANCED-INTRO"


class TestEnhanceHook:
    async def test_enhances_when_flag_on(self) -> None:
        enhancer = _StubEnhancer()
        assembler = DigestAssembler(
            frequency=FrequencyController(clock=_FixedClock()),
            enhancer=enhancer,  # type: ignore[arg-type]
        )
        sub = StubSubscription(
            channel="email",
            frequency="daily",
            channel_config={"to_addr": "u@x.io", "template_config": {"enhance": True}},
        )
        result = await assembler.assemble(sub, [StubContent(id="c1", title="AI")])
        assert enhancer.called is True
        assert result is not None
        assert "ENHANCED-INTRO" in result.body

    async def test_not_enhanced_when_flag_absent(self) -> None:
        enhancer = _StubEnhancer()
        assembler = DigestAssembler(
            frequency=FrequencyController(clock=_FixedClock()),
            enhancer=enhancer,  # type: ignore[arg-type]
        )
        sub = StubSubscription(channel="email", frequency="daily")
        result = await assembler.assemble(sub, [StubContent(id="c1", title="AI")])
        assert enhancer.called is False
        assert result is not None
        assert "ENHANCED-INTRO" not in result.body


class _StubRenderer:
    """A stub freeform renderer returning a recognizable body."""

    async def render(self, **kwargs: Any) -> str:
        return "LLM-FREEFORM-BODY"


class TestRenderMode:
    async def test_default_mode_is_code(self) -> None:
        result = await _assembler().assemble(
            StubSubscription(frequency="daily"), [StubContent(id="c1", title="AI 速览")]
        )
        assert result is not None
        assert result.render_mode == "code"
        # code body comes from the Jinja template, not the freeform renderer.
        assert "LLM-FREEFORM-BODY" not in result.body

    async def test_llm_freeform_uses_renderer_and_labels_mode(self) -> None:
        assembler = DigestAssembler(
            frequency=FrequencyController(clock=_FixedClock()),
            llm_renderer=_StubRenderer(),  # type: ignore[arg-type]
        )
        sub = StubSubscription(
            channel="email",
            frequency="daily",
            channel_config={
                "to_addr": "u@x.io",
                "template_config": {"render_mode": "llm-freeform"},
            },
        )
        result = await assembler.assemble(sub, [StubContent(id="c1", title="AI 速览")])
        assert result is not None
        assert result.body == "LLM-FREEFORM-BODY"
        assert result.render_mode == "llm-freeform"

    async def test_freeform_without_renderer_downgrades_to_code(self) -> None:
        # render_mode requests freeform but no llm_renderer is wired.
        assembler = DigestAssembler(frequency=FrequencyController(clock=_FixedClock()))
        sub = StubSubscription(
            channel="email",
            frequency="daily",
            channel_config={
                "to_addr": "u@x.io",
                "template_config": {"render_mode": "llm-freeform"},
            },
        )
        result = await assembler.assemble(sub, [StubContent(id="c1", title="AI 速览")])
        assert result is not None
        assert result.render_mode == "code"
        assert "AI 速览" in result.body

    async def test_llm_assisted_enhances_then_code_renders(self) -> None:
        enhancer = _StubEnhancer()
        assembler = DigestAssembler(
            frequency=FrequencyController(clock=_FixedClock()),
            enhancer=enhancer,  # type: ignore[arg-type]
            llm_renderer=_StubRenderer(),  # type: ignore[arg-type]
        )
        sub = StubSubscription(
            channel="email",
            frequency="daily",
            channel_config={
                "to_addr": "u@x.io",
                "template_config": {"render_mode": "llm-assisted"},
            },
        )
        result = await assembler.assemble(sub, [StubContent(id="c1", title="AI")])
        assert result is not None
        assert enhancer.called is True
        assert result.render_mode == "llm-assisted"
        # assisted = enhance the bundle, then code-render (not the freeform body).
        assert result.body != "LLM-FREEFORM-BODY"
        assert "ENHANCED-INTRO" in result.body
