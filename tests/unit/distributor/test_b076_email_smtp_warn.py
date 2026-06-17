"""Tests for AC-1 (G-007): SMTP port↔TLS consistency warning in EmailDistributor."""

from __future__ import annotations

import logging

import pytest


class TestSmtpPortTlsWarn:
    """AC-1: from_env() emits WARNING when port and TLS mode are inconsistent."""

    def _make_env(
        self, monkeypatch: pytest.MonkeyPatch, port: str, use_tls: str
    ) -> None:
        monkeypatch.setenv("IS_SMTP_HOST", "mail.test.com")
        monkeypatch.setenv("IS_SMTP_USER", "user@test.com")
        monkeypatch.setenv("IS_SMTP_PASSWORD", "secret")
        monkeypatch.setenv("IS_SMTP_PORT", port)
        monkeypatch.setenv("IS_SMTP_USE_TLS", use_tls)

    def test_587_with_use_tls_true_emits_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 587 with use_tls=true: WARNING logged, distributor still constructed."""
        self._make_env(monkeypatch, "587", "true")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            distributor = EmailDistributor.from_env()

        assert isinstance(distributor, EmailDistributor)
        warning_msgs = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(
            "587" in m or "STARTTLS" in m or "inconsistent" in m.lower()
            for m in warning_msgs
        ), f"Expected WARNING about port/TLS mismatch, got: {warning_msgs}"

    def test_465_with_use_tls_false_emits_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 465 with use_tls=false: WARNING logged, distributor constructed."""
        self._make_env(monkeypatch, "465", "false")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            distributor = EmailDistributor.from_env()

        assert isinstance(distributor, EmailDistributor)
        warning_msgs = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert any(
            "465" in m or "implicit" in m.lower() or "inconsistent" in m.lower()
            for m in warning_msgs
        ), f"Expected WARNING about port 465/TLS mismatch, got: {warning_msgs}"

    def test_consistent_465_true_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 465 + use_tls=true is consistent — no WARNING."""
        self._make_env(monkeypatch, "465", "true")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            EmailDistributor.from_env()

        smtp_module_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "intellisource.distributor.channels.email" in r.name
        ]
        assert smtp_module_warnings == [], (
            f"No WARNING expected for 465+TLS, but got: {smtp_module_warnings}"
        )

    def test_consistent_587_false_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 587 + use_tls=false (STARTTLS) is consistent — no WARNING."""
        self._make_env(monkeypatch, "587", "false")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            EmailDistributor.from_env()

        smtp_module_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "intellisource.distributor.channels.email" in r.name
        ]
        assert smtp_module_warnings == [], (
            f"No WARNING expected for 587+STARTTLS, but got: {smtp_module_warnings}"
        )

    def test_consistent_1025_false_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 1025 + use_tls=false (local dev plain) is consistent — no WARNING."""
        self._make_env(monkeypatch, "1025", "false")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            EmailDistributor.from_env()

        smtp_module_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "intellisource.distributor.channels.email" in r.name
        ]
        assert smtp_module_warnings == [], (
            f"No WARNING expected for 1025+plain, but got: {smtp_module_warnings}"
        )

    def test_consistent_25_false_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Port 25 + use_tls=false (plain) is consistent — no WARNING."""
        self._make_env(monkeypatch, "25", "false")
        from intellisource.distributor.channels.email import EmailDistributor

        with caplog.at_level(logging.WARNING):
            EmailDistributor.from_env()

        smtp_module_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "intellisource.distributor.channels.email" in r.name
        ]
        assert smtp_module_warnings == [], (
            f"No WARNING expected for 25+plain, but got: {smtp_module_warnings}"
        )
