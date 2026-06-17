"""MetricsCollector labeled counter subsystem — RED/GREEN tests.

Acceptance criteria:
  AC-B005-1  register_labeled_counter + increment_labeled_counter accumulate per label.
  AC-B005-2  Different label combinations accumulate independently.
  AC-B005-3  Idempotent re-register with same labelnames; ValueError on mismatch.
  AC-B005-4  get_labeled_counter_value returns 0.0 for unset labels;
             iter_labeled_counters yields (name, labels, value) full set.
  AC-B005-5  amount parameter supports non-integer increments (token counts etc.).
"""

from __future__ import annotations

import pytest

from intellisource.observability.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    MetricsCollector._instance = None
    yield  # type: ignore[misc]
    MetricsCollector._instance = None


# ---------------------------------------------------------------------------
# AC-B005-1  Basic register + increment accumulates per label combination.
# ---------------------------------------------------------------------------


class TestLabeledCounterBasic:
    """register_labeled_counter + increment_labeled_counter round-trip."""

    def test_register_and_increment_single_label(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})

        value = mc.get_labeled_counter_value("pushes_total", {"channel": "email"})
        assert value == 2.0

    def test_increment_accumulates_across_multiple_calls(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        for _ in range(5):
            mc.increment_labeled_counter("pushes_total", labels={"channel": "wechat"})

        value = mc.get_labeled_counter_value("pushes_total", {"channel": "wechat"})
        assert value == 5.0


# ---------------------------------------------------------------------------
# AC-B005-2  Different label combinations accumulate independently.
# ---------------------------------------------------------------------------


class TestLabeledCounterIndependence:
    """Each distinct label combination maintains its own counter series."""

    def test_two_channels_accumulate_independently(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])

        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})
        mc.increment_labeled_counter("pushes_total", labels={"channel": "wechat"})
        mc.increment_labeled_counter("pushes_total", labels={"channel": "wechat"})

        email_val = mc.get_labeled_counter_value("pushes_total", {"channel": "email"})
        wechat_val = mc.get_labeled_counter_value("pushes_total", {"channel": "wechat"})
        assert email_val == 1.0
        assert wechat_val == 2.0

    def test_compound_labels_accumulate_per_combination(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])

        mc.increment_labeled_counter(
            "pushes_total", labels={"channel": "email", "status": "sent"}
        )
        mc.increment_labeled_counter(
            "pushes_total", labels={"channel": "email", "status": "failed"}
        )
        mc.increment_labeled_counter(
            "pushes_total", labels={"channel": "wework", "status": "sent"}
        )

        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "sent"}
            )
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "failed"}
            )
            == 1.0
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "wework", "status": "sent"}
            )
            == 1.0
        )
        # Never-touched combination returns 0.0
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "wework", "status": "failed"}
            )
            == 0.0
        )


# ---------------------------------------------------------------------------
# AC-B005-3  Idempotent re-register; ValueError on labelnames mismatch.
# ---------------------------------------------------------------------------


class TestLabeledCounterRegisterIdempotency:
    """register_labeled_counter is idempotent for same labelnames."""

    def test_re_register_same_labelnames_is_idempotent(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("llm_calls_total", labelnames=["model"])
        mc.increment_labeled_counter("llm_calls_total", labels={"model": "gpt-4o-mini"})

        # Re-register must not reset the counter
        mc.register_labeled_counter("llm_calls_total", labelnames=["model"])

        value = mc.get_labeled_counter_value(
            "llm_calls_total", {"model": "gpt-4o-mini"}
        )
        assert value == 1.0, "Re-register with same labelnames must preserve data"

    def test_re_register_different_labelnames_raises_value_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("llm_calls_total", labelnames=["model"])

        with pytest.raises(ValueError, match="labelnames"):
            mc.register_labeled_counter(
                "llm_calls_total", labelnames=["model", "status"]
            )


# ---------------------------------------------------------------------------
# AC-B005-4  get_labeled_counter_value returns 0.0 for never-set series;
#            iter_labeled_counters yields full (name, labels, value) set.
# ---------------------------------------------------------------------------


class TestLabeledCounterReadback:
    """Read-back API: unset returns 0.0; iter yields full series."""

    def test_unset_label_combination_returns_zero(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])

        # Never incremented — must return 0.0 (not raise)
        value = mc.get_labeled_counter_value("pushes_total", {"channel": "email"})
        assert value == 0.0

    def test_iter_labeled_counters_yields_all_series(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})
        mc.increment_labeled_counter("pushes_total", labels={"channel": "wechat"})
        mc.increment_labeled_counter("pushes_total", labels={"channel": "wechat"})

        results = mc.iter_labeled_counters()
        assert len(results) == 1  # one metric name

        name, series = results[0]
        assert name == "pushes_total"
        # series must contain both label combinations
        label_keys = set(series.keys())
        assert "channel=email" in label_keys
        assert "channel=wechat" in label_keys
        assert series["channel=email"] == 1.0
        assert series["channel=wechat"] == 2.0

    def test_iter_labeled_counters_multiple_metrics(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        mc.register_labeled_counter("llm_calls_total", labelnames=["model"])
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})
        mc.increment_labeled_counter(
            "llm_calls_total", labels={"model": "claude-sonnet-4-20250514"}
        )

        results = mc.iter_labeled_counters()
        names = {r[0] for r in results}
        assert "pushes_total" in names
        assert "llm_calls_total" in names


# ---------------------------------------------------------------------------
# AC-B005-5  amount parameter supports non-integer increments.
# ---------------------------------------------------------------------------


class TestLabeledCounterAmount:
    """increment_labeled_counter respects non-default amount values."""

    def test_default_amount_is_one(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("llm_calls_total", labelnames=["model"])
        mc.increment_labeled_counter("llm_calls_total", labels={"model": "gpt-4o"})

        assert (
            mc.get_labeled_counter_value("llm_calls_total", {"model": "gpt-4o"}) == 1.0
        )

    def test_token_count_amount(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("llm_tokens_total", labelnames=["model"])
        mc.increment_labeled_counter(
            "llm_tokens_total", labels={"model": "gpt-4o"}, amount=1234
        )
        mc.increment_labeled_counter(
            "llm_tokens_total", labels={"model": "gpt-4o"}, amount=567
        )

        value = mc.get_labeled_counter_value("llm_tokens_total", {"model": "gpt-4o"})
        assert value == 1801.0

    def test_float_amount(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("cost_total", labelnames=["provider"])
        mc.increment_labeled_counter(
            "cost_total", labels={"provider": "openai"}, amount=0.005
        )
        mc.increment_labeled_counter(
            "cost_total", labels={"provider": "openai"}, amount=0.003
        )

        value = mc.get_labeled_counter_value("cost_total", {"provider": "openai"})
        assert abs(value - 0.008) < 1e-9


# ---------------------------------------------------------------------------
# AC-B005-6  /metrics endpoint renders labeled counter Prometheus text.
# ---------------------------------------------------------------------------


class TestLabeledCounterMetricsEndpoint:
    """Prometheus text output includes labeled counter lines with correct TYPE."""

    @pytest.mark.asyncio
    async def test_metrics_response_contains_labeled_counter_line(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from intellisource.api.routers.system import router

        app = FastAPI()
        app.include_router(router)

        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})

        app.state.metrics_collector = mc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        body = resp.text
        assert 'pushes_total{channel="email"}' in body
        assert "# TYPE pushes_total counter" in body

    @pytest.mark.asyncio
    async def test_metrics_response_labeled_counter_value(self) -> None:
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from intellisource.api.routers.system import router

        app = FastAPI()
        app.include_router(router)

        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})

        app.state.metrics_collector = mc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        body = resp.text
        # The value line should contain the counter value
        assert 'pushes_total{channel="email"} 1' in body


# ---------------------------------------------------------------------------
# labelnames enforcement — typo / wrong keys raise KeyError.
# ---------------------------------------------------------------------------


class TestLabeledCounterLabelValidation:
    """increment_labeled_counter and get_labeled_counter_value enforce labelnames."""

    def test_increment_typo_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])
        with pytest.raises(KeyError, match="channel.*status|expects labelnames"):
            mc.increment_labeled_counter(
                "pushes_total", labels={"chanel": "email", "status": "sent"}
            )

    def test_increment_missing_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])
        with pytest.raises(KeyError, match="expects labelnames"):
            mc.increment_labeled_counter("pushes_total", labels={"channel": "email"})

    def test_increment_extra_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel"])
        with pytest.raises(KeyError, match="expects labelnames"):
            mc.increment_labeled_counter(
                "pushes_total", labels={"channel": "email", "status": "sent"}
            )

    def test_get_value_typo_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])
        with pytest.raises(KeyError, match="expects labelnames"):
            mc.get_labeled_counter_value(
                "pushes_total", labels={"chanel": "email", "status": "sent"}
            )

    def test_increment_error_message_contains_expected_and_actual(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])
        with pytest.raises(KeyError) as exc_info:
            mc.increment_labeled_counter(
                "pushes_total", labels={"chanel": "email", "status": "sent"}
            )
        msg = str(exc_info.value)
        assert "channel" in msg
        assert "status" in msg

    def test_correct_labels_do_not_raise(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_counter("pushes_total", labelnames=["channel", "status"])
        mc.increment_labeled_counter(
            "pushes_total", labels={"channel": "email", "status": "sent"}
        )
        assert (
            mc.get_labeled_counter_value(
                "pushes_total", {"channel": "email", "status": "sent"}
            )
            == 1.0
        )
