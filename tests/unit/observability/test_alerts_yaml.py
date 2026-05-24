"""Static validation of docker/prometheus/alerts.yml (F-24).

The full alert rule semantics live in Prometheus' ``promtool`` (not part of
this project's test stack). We assert the YAML shape, required severity /
component labels, and that every alert references a metric this codebase
actually emits — so a renamed metric here surfaces as a test failure
instead of silent dashboard rot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ALERTS_PATH = Path(__file__).parents[3] / "docker" / "prometheus" / "alerts.yml"
PROM_CONFIG_PATH = (
    Path(__file__).parents[3] / "docker" / "prometheus" / "prometheus.yml"
)

# Metrics produced by the codebase. Renaming these requires updating both the
# emitter and this list together, which is the entire point of the assertion.
EMITTED_METRICS: set[str] = {
    "http_requests_total",
    "http_request_duration_seconds",
    "llm_calls_total",
    "llm_call_failures_total",
    "llm_call_latency_seconds",
    "llm_circuit_open",
    "pushes_total",
    "pushes_sent_total",
    "pushes_failed_total",
    "pushes_skipped_total",
    "celery_tasks_total",
    "celery_task_failures_total",
    "celery_task_duration_seconds",
    "scheduler_beat_sync_failed_total",
    # Prometheus built-in target liveness
    "up",
}

# Histogram-derived metric names that don't appear directly but are emitted as
# `<name>_bucket` / `<name>_count` / `<name>_sum` by Prometheus tooling.
HISTOGRAM_SUFFIXES = ("_bucket", "_count", "_sum")


def _extract_metric_refs(expr: str) -> set[str]:
    """Pull metric names out of a PromQL expression."""
    raw: set[str] = set(re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", expr))
    # Drop PromQL keywords / functions that look like metric names
    return raw - {
        "rate",
        "irate",
        "increase",
        "histogram_quantile",
        "clamp_min",
        "clamp_max",
        "sum",
        "avg",
        "max",
        "min",
        "by",
        "without",
        "on",
        "group_left",
        "group_right",
        "and",
        "or",
        "unless",
        "if",
        "ignoring",
        "job",
        "le",
        "instance",
        "intellisource-api",
    }


def _load_alerts() -> list[dict]:
    with ALERTS_PATH.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rules: list[dict] = []
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            rule["__group_name"] = group["name"]
            rules.append(rule)
    return rules


def test_alerts_file_exists() -> None:
    assert ALERTS_PATH.is_file(), f"alerts.yml missing at {ALERTS_PATH}"


def test_prometheus_config_references_alerts_file() -> None:
    with PROM_CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert "rule_files" in cfg
    assert any("alerts.yml" in str(rf) for rf in cfg["rule_files"]), (
        "prometheus.yml must list alerts.yml in rule_files"
    )


@pytest.fixture(scope="module")
def alert_rules() -> list[dict]:
    return _load_alerts()


def test_every_alert_has_severity_and_component(alert_rules: list[dict]) -> None:
    for rule in alert_rules:
        labels = rule.get("labels", {})
        assert "severity" in labels, f"{rule['alert']}: missing labels.severity"
        assert labels["severity"] in {"critical", "warning"}, (
            f"{rule['alert']}: severity must be critical/warning"
        )
        assert "component" in labels, f"{rule['alert']}: missing labels.component"


def test_every_alert_has_summary_and_description(alert_rules: list[dict]) -> None:
    for rule in alert_rules:
        ann = rule.get("annotations", {})
        assert "summary" in ann, f"{rule['alert']}: missing annotations.summary"
        assert "description" in ann, f"{rule['alert']}: missing annotations.description"


def test_alert_metric_names_are_emitted(alert_rules: list[dict]) -> None:
    """Every metric name referenced by an alert must be emitted by the codebase.

    A metric on the RHS that nobody emits silently never fires — that is
    exactly the failure mode F-24 is meant to prevent.
    """
    for rule in alert_rules:
        expr = rule["expr"]
        referenced = _extract_metric_refs(expr)
        # Filter to identifiers that look like metric names: contain '_' or
        # are 'up'. This drops PromQL labels (e.g. 'severity', 'component').
        candidate_metrics = {r for r in referenced if r == "up" or "_" in r}
        for name in candidate_metrics:
            base = name
            for suffix in HISTOGRAM_SUFFIXES:
                if base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            if base in EMITTED_METRICS:
                continue
            # Allow latency_seconds histogram base
            latency_bases = {
                "http_request_duration_seconds",
                "llm_call_latency_seconds",
            }
            if base.endswith("_seconds") and base in latency_bases:
                continue
            pytest.fail(
                f"{rule['alert']}: expression references metric {name!r} "
                f"(base {base!r}) which is not in EMITTED_METRICS — either "
                f"add it to the emitter or remove the alert"
            )


def test_alert_names_unique(alert_rules: list[dict]) -> None:
    names = [r["alert"] for r in alert_rules]
    assert len(names) == len(set(names)), f"duplicate alert names: {names}"


def test_critical_alerts_present() -> None:
    """F-24 explicit asks: at least one alert each for circuit-open and push-failure."""
    rules = _load_alerts()
    names = {r["alert"] for r in rules}
    assert "LLMCircuitOpen" in names
    assert "PushFailureRateHigh" in names
    # The "health 5min" requirement collapses to API liveness at the Prom layer.
    assert "ApiInstanceDown" in names
