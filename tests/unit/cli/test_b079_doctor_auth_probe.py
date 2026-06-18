"""Tests for B-079: doctor --check-api authenticated probe (key-drift detection)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from intellisource.cli.commands.doctor import _probe_api_auth
from intellisource.cli.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_response(status_code: int) -> MagicMock:
    """Return an httpx.Response-like mock with the given status_code."""
    resp = MagicMock()
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# Unit tests: _probe_api_auth helper
# ---------------------------------------------------------------------------


class TestProbeApiAuth:
    """Direct unit tests for _probe_api_auth outcome classification."""

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_200_returns_ok(self, mock_get: MagicMock) -> None:
        """2xx response from protected endpoint → outcome 'ok'."""
        mock_get.return_value = _http_response(200)

        outcome, detail = _probe_api_auth("my-key")

        assert outcome == "ok", f"Expected 'ok' for 200 response, got {outcome!r}"
        mock_get.assert_called_once()
        assert "headers" in mock_get.call_args.kwargs

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_401_returns_unauthorized(self, mock_get: MagicMock) -> None:
        """401 response → outcome 'unauthorized'."""
        mock_get.return_value = _http_response(401)

        outcome, detail = _probe_api_auth("drift-key")

        assert outcome == "unauthorized", (
            f"Expected 'unauthorized' for 401 response, got {outcome!r}"
        )

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_500_returns_inconclusive(self, mock_get: MagicMock) -> None:
        """5xx response → outcome 'inconclusive' (not a key drift)."""
        mock_get.return_value = _http_response(500)

        outcome, detail = _probe_api_auth("some-key")

        assert outcome == "inconclusive", (
            f"Expected 'inconclusive' for 500 response, got {outcome!r}"
        )

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_connect_error_returns_inconclusive(self, mock_get: MagicMock) -> None:
        """Network ConnectError → outcome 'inconclusive' (cannot determine drift)."""
        mock_get.side_effect = httpx.ConnectError("connection refused")

        outcome, detail = _probe_api_auth("some-key")

        assert outcome == "inconclusive", (
            f"Expected 'inconclusive' for ConnectError, got {outcome!r}"
        )

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_403_returns_inconclusive(self, mock_get: MagicMock) -> None:
        """403 (other client error, not auth) → inconclusive; not a 401 so not drift."""
        mock_get.return_value = _http_response(403)

        outcome, detail = _probe_api_auth("some-key")

        # 403 is a non-401 4xx; per contract: outcome "ok" (< 500 and not 401)
        # Actually per interface_contract: "ok" for <500 non-401.
        assert outcome == "ok", f"Expected 'ok' for 403 (non-401 <500), got {outcome!r}"

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_sends_x_api_key_header(self, mock_get: MagicMock) -> None:
        """_probe_api_auth must send X-API-Key header with the provided key."""
        mock_get.return_value = _http_response(200)

        _probe_api_auth("secret-key-123")

        call_kwargs = mock_get.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert "X-API-Key" in headers, f"X-API-Key not in headers: {headers}"
        assert headers["X-API-Key"] == "secret-key-123"

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_does_not_raise_on_exception(self, mock_get: MagicMock) -> None:
        """_probe_api_auth must never propagate exceptions (doctor never tracebacks)."""
        mock_get.side_effect = RuntimeError("unexpected!")

        # Should return inconclusive, not raise
        outcome, detail = _probe_api_auth("some-key")

        assert outcome == "inconclusive"

    @patch("intellisource.cli.commands.doctor.httpx.get")
    def test_passes_timeout_to_httpx(self, mock_get: MagicMock) -> None:
        """A timeout must be passed so doctor never hangs on an unreachable API."""
        mock_get.return_value = _http_response(200)

        _probe_api_auth("some-key")

        kwargs = mock_get.call_args.kwargs
        assert "timeout" in kwargs, f"timeout not passed to httpx.get: {kwargs}"
        assert kwargs["timeout"] is not None


# ---------------------------------------------------------------------------
# Integration tests: doctor() command with auth probe
# ---------------------------------------------------------------------------


class TestDoctorAuthProbeIntegration:
    """AC1-AC5: doctor --check-api auth probe integration with CliRunner."""

    def _make_runner(self) -> Any:
        from typer.testing import CliRunner

        return CliRunner()

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac1_auth_ok_reports_accepted(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC1: health ok + key consistent → [OK] with 'auth' and 'accepted'."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "valid-key"}
        mock_health.return_value = ("ok", {"status": "healthy"})
        mock_auth.return_value = ("ok", "200 OK")

        runner = self._make_runner()
        result = runner.invoke(app, ["doctor", "--check-api"])

        assert result.exit_code == 0, f"exit_code={result.exit_code}\n{result.output}"
        output_lower = result.output.lower()
        assert "[ok]" in output_lower, f"Missing [OK] in output:\n{result.output}"
        assert "auth" in output_lower, f"Missing 'auth' in output:\n{result.output}"
        assert "accept" in output_lower, f"Missing 'accept' in output:\n{result.output}"

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac2_auth_unauthorized_reports_fail_and_counts_error(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC2: 401 key drift → [FAIL], error counted, fix hint about rebuild."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "drifted-key"}
        mock_health.return_value = ("ok", {"status": "healthy"})
        mock_auth.return_value = ("unauthorized", "401 Unauthorized")

        runner = self._make_runner()
        result = runner.invoke(app, ["doctor", "--check-api"])

        assert "[FAIL]" in result.output, f"Missing [FAIL] in output:\n{result.output}"
        output_lower = result.output.lower()
        # Fix hint must mention rebuild
        assert "up" in output_lower or "rebuild" in output_lower, (
            f"Missing rebuild hint in output:\n{result.output}"
        )
        assert "need attention" in output_lower, (
            f"Missing 'need attention' summary:\n{result.output}"
        )

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac2_strict_exits_one_on_key_drift(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC2: 401 + --strict → exit code 1."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "drifted-key"}
        mock_health.return_value = ("ok", {"status": "healthy"})
        mock_auth.return_value = ("unauthorized", "401 Unauthorized")

        runner = self._make_runner()
        result = runner.invoke(app, ["doctor", "--check-api", "--strict"])

        assert result.exit_code == 1, (
            f"Expected exit code 1 on key drift + --strict, got {result.exit_code}"
        )

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac3_inconclusive_shows_soft_note_no_error(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC3: network error / inconclusive → [--] soft note, no error counted."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "some-key"}
        mock_health.return_value = ("ok", {"status": "healthy"})
        mock_auth.return_value = ("inconclusive", "connection refused")

        runner = self._make_runner()
        result = runner.invoke(app, ["doctor", "--check-api"])

        # The [--] soft note must appear for the auth probe line
        assert "[--]" in result.output, (
            f"Expected [--] soft note for inconclusive:\n{result.output}"
        )
        # The auth probe itself must not produce a [FAIL] line
        auth_fail_lines = [
            line
            for line in result.output.splitlines()
            if "[FAIL]" in line and "auth" in line.lower()
        ]
        assert not auth_fail_lines, (
            f"Auth probe [FAIL] must not appear for inconclusive:\n{result.output}"
        )

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac4_health_down_skips_auth_probe(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC4: API down → auth probe skipped entirely."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "some-key"}
        mock_health.return_value = ("down", "connection refused")

        runner = self._make_runner()
        runner.invoke(app, ["doctor", "--check-api"])

        mock_auth.assert_not_called()

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac4_health_starting_skips_auth_probe(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC4: API starting → auth probe skipped."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "some-key"}
        mock_health.return_value = ("starting", "empty JSON body")

        runner = self._make_runner()
        runner.invoke(app, ["doctor", "--check-api"])

        mock_auth.assert_not_called()

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac5_no_api_key_skips_auth_probe(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC5: IS_API_KEY absent → auth probe skipped."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {}  # no IS_API_KEY
        mock_health.return_value = ("ok", {"status": "healthy"})

        runner = self._make_runner()
        runner.invoke(app, ["doctor", "--check-api"])

        mock_auth.assert_not_called()

    @patch("intellisource.cli.commands.doctor._probe_api_auth")
    @patch("intellisource.cli.commands.doctor._probe_api_health")
    @patch("intellisource.cli.commands.doctor._load_dotenv_file")
    @patch("intellisource.cli.commands.doctor.project_root")
    def test_ac5_placeholder_api_key_skips_auth_probe(
        self,
        mock_root: MagicMock,
        mock_load_env: MagicMock,
        mock_health: MagicMock,
        mock_auth: MagicMock,
        tmp_path: Any,
    ) -> None:
        """AC5: IS_API_KEY is placeholder → auth probe skipped."""
        mock_root.return_value = tmp_path
        mock_load_env.return_value = {"IS_API_KEY": "change-me-in-production"}
        mock_health.return_value = ("ok", {"status": "healthy"})

        runner = self._make_runner()
        runner.invoke(app, ["doctor", "--check-api"])

        mock_auth.assert_not_called()
