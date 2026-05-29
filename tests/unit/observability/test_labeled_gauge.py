"""R-001: labeled gauge labelnames enforcement — RED/GREEN tests.

Acceptance criteria (R-001 gauge sub-system parity):
  AC-R001-G1  register_labeled_gauge with labelnames is idempotent for same labelnames.
  AC-R001-G2  re-register with different labelnames raises ValueError.
  AC-R001-G3  set_labeled_gauge with wrong label keys raises KeyError (schema drift
              blocked).
  AC-R001-G4  get_labeled_gauge_value with wrong label keys raises KeyError.
  AC-R001-G5  Correct label keys continue to work normally.
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
# AC-R001-G1  Idempotent re-register with same labelnames.
# ---------------------------------------------------------------------------


class TestLabeledGaugeRegisterIdempotency:
    """register_labeled_gauge is idempotent for same labelnames."""

    def test_re_register_same_labelnames_preserves_data(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("my_gauge", labelnames=["component"])
        mc.set_labeled_gauge("my_gauge", {"component": "db"}, 1.0)

        mc.register_labeled_gauge("my_gauge", labelnames=["component"])

        assert mc.get_labeled_gauge_value("my_gauge", {"component": "db"}) == 1.0


# ---------------------------------------------------------------------------
# AC-R001-G2  Different labelnames on re-register raises ValueError.
# ---------------------------------------------------------------------------


class TestLabeledGaugeRegisterMismatch:
    """register_labeled_gauge raises ValueError on labelnames conflict."""

    def test_re_register_different_labelnames_raises_value_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("my_gauge", labelnames=["component"])

        with pytest.raises(ValueError, match="labelnames"):
            mc.register_labeled_gauge("my_gauge", labelnames=["component", "region"])


# ---------------------------------------------------------------------------
# AC-R001-G3  set_labeled_gauge enforces label key schema.
# ---------------------------------------------------------------------------


class TestLabeledGaugeSetValidation:
    """set_labeled_gauge raises KeyError when label keys deviate from labelnames."""

    def test_set_wrong_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component"])

        with pytest.raises(KeyError, match="expects labelnames"):
            mc.set_labeled_gauge("health_status", {"componnt": "db"}, 0.0)

    def test_set_extra_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component"])

        with pytest.raises(KeyError, match="expects labelnames"):
            mc.set_labeled_gauge(
                "health_status", {"component": "db", "region": "us"}, 0.0
            )

    def test_set_missing_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component", "region"])

        with pytest.raises(KeyError, match="expects labelnames"):
            mc.set_labeled_gauge("health_status", {"component": "db"}, 0.0)

    def test_error_message_contains_expected_and_actual(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component"])

        with pytest.raises(KeyError) as exc_info:
            mc.set_labeled_gauge("health_status", {"componnt": "db"}, 0.0)
        msg = str(exc_info.value)
        assert "component" in msg


# ---------------------------------------------------------------------------
# AC-R001-G4  get_labeled_gauge_value enforces label key schema.
# ---------------------------------------------------------------------------


class TestLabeledGaugeGetValidation:
    """get_labeled_gauge_value raises KeyError when label keys deviate."""

    def test_get_wrong_key_raises_key_error(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component"])
        mc.set_labeled_gauge("health_status", {"component": "db"}, 0.0)

        with pytest.raises(KeyError, match="expects labelnames"):
            mc.get_labeled_gauge_value("health_status", {"componnt": "db"})


# ---------------------------------------------------------------------------
# AC-R001-G5  Correct label keys continue to work normally.
# ---------------------------------------------------------------------------


class TestLabeledGaugeCorrectUsage:
    """Valid label keys pass through without error after labelnames enforcement."""

    def test_correct_labels_set_and_get(self) -> None:
        mc = MetricsCollector.get_instance()
        mc.register_labeled_gauge("health_status", labelnames=["component"])
        mc.set_labeled_gauge("health_status", {"component": "db"}, 0.0)

        assert mc.get_labeled_gauge_value("health_status", {"component": "db"}) == 0.0

    def test_health_checker_still_works_with_labelnames(self) -> None:
        """HealthChecker passes labelnames=["component"] to register_labeled_gauge."""
        from intellisource.observability.health import HealthChecker

        mc = MetricsCollector.get_instance()
        checker = HealthChecker(metrics_collector=mc)
        assert isinstance(checker, HealthChecker)
        # Constructing with a collector must register the health gauge under the
        # "component" label, so a set/get round-trip on that label must succeed.
        mc.set_labeled_gauge("intellisource_health_status", {"component": "db"}, 0.0)
        assert (
            mc.get_labeled_gauge_value(
                "intellisource_health_status", {"component": "db"}
            )
            == 0.0
        )
