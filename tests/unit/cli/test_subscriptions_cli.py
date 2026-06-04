"""Tests for `intellisource subscriptions` CLI subcommands (B-055)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from intellisource.cli.main import app


def _mock_response(*, status_code: int = 200, json_data: Any = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = json.dumps(json_data) if json_data is not None else ""
    return resp


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    @patch("intellisource.cli.main.httpx")
    def test_list_calls_get_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(json_data={"items": []})
        result = runner.invoke(app, ["subscriptions", "list", "--json"])
        assert result.exit_code == 0
        called_url = mock_httpx.get.call_args.args[0]
        assert called_url.endswith("/api/v1/subscriptions")

    @patch("intellisource.cli.main.httpx")
    def test_list_emits_json_when_flag_set(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        items = [{"id": "1", "name": "a", "channel": "wework"}]
        mock_httpx.get.return_value = _mock_response(
            json_data={"items": items, "next_cursor": None, "has_more": False}
        )
        result = runner.invoke(app, ["subscriptions", "list", "--json"])
        body = json.loads(result.stdout.strip())
        assert body["items"][0]["channel"] == "wework"


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestAdd:
    @patch("intellisource.cli.main.httpx")
    def test_add_wework_posts_subscription_config_payload(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=201,
            json_data={
                "id": "abc",
                "name": "ai-digest",
                "channel": "wework",
                "channel_config": {"user_id": "@all", "msg_type": "markdown"},
                "match_rules": {"tags": ["ai"]},
            },
        )
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "ai-digest",
                "--channel",
                "wework",
                "--tags",
                "ai",
                "--json",
            ],
            input="@all\nmarkdown\n",  # user_id, msg_type prompts
        )
        assert result.exit_code == 0, result.stdout
        # Verify POST URL + payload shape align with SubscriptionConfig
        call = mock_httpx.post.call_args
        assert call.args[0].endswith("/api/v1/subscriptions")
        payload = call.kwargs["json"]
        assert payload["name"] == "ai-digest"
        assert payload["channel"] == "wework"
        assert payload["channel_config"]["user_id"] == "@all"
        assert payload["channel_config"]["msg_type"] == "markdown"
        assert payload["match_rules"]["tags"] == ["ai"]
        assert "frequency" in payload  # SubscriptionConfig has frequency field

    @patch("intellisource.cli.main.httpx")
    def test_add_email_collects_to_addr(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=201, json_data={"id": "x", "name": "n", "channel": "email"}
        )
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "n",
                "--channel",
                "email",
                "--tags",
                "tech",
                "--json",
            ],
            input="user@example.com\n",  # to_addr prompt
        )
        assert result.exit_code == 0
        payload = mock_httpx.post.call_args.kwargs["json"]
        assert payload["channel_config"]["to_addr"] == "user@example.com"

    @patch("intellisource.cli.main.httpx")
    def test_add_daily_folds_template_and_render_mode(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=201, json_data={"id": "x", "name": "d", "channel": "email"}
        )
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "d",
                "--channel",
                "email",
                "--frequency",
                "daily",
                "--tags",
                "ai",
                "--template",
                "daily-brief",
                "--render-mode",
                "llm-freeform",
                "--json",
            ],
            input="a@b.com\n",  # to_addr prompt
        )
        assert result.exit_code == 0, result.stdout
        cc = mock_httpx.post.call_args.kwargs["json"]["channel_config"]
        assert cc.get("template") == "daily-brief"
        assert cc.get("template_config", {}).get("render_mode") == "llm-freeform"

    @patch("intellisource.cli.main.httpx")
    def test_add_realtime_ignores_render_mode(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=201, json_data={"id": "r", "name": "r", "channel": "email"}
        )
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "r",
                "--channel",
                "email",
                "--frequency",
                "realtime",
                "--tags",
                "ai",
                "--render-mode",
                "llm-freeform",
                "--json",
            ],
            input="a@b.com\n",
        )
        assert result.exit_code == 0, result.stdout
        cc = mock_httpx.post.call_args.kwargs["json"]["channel_config"]
        assert "template_config" not in cc

    @patch("intellisource.cli.main.httpx")
    def test_add_daily_invalid_render_mode_aborts_code_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "d",
                "--channel",
                "email",
                "--frequency",
                "daily",
                "--tags",
                "ai",
                "--render-mode",
                "llm_freeform",  # underscore typo
            ],
            input="a@b.com\n",
        )
        assert result.exit_code == 2
        assert "render_mode must be one of" in result.stdout
        mock_httpx.post.assert_not_called()

    @patch("intellisource.cli.main.httpx")
    def test_add_invalid_channel_aborts_with_code_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            app,
            ["subscriptions", "add", "--name", "n", "--channel", "telegram"],
        )
        assert result.exit_code == 2
        assert "channel must be wework/wechat/email" in result.stdout
        mock_httpx.post.assert_not_called()

    @patch("intellisource.cli.main.httpx")
    def test_add_propagates_422_with_validator_message(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=422, json_data={"detail": "email channel requires to_addr"}
        )
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "add",
                "--name",
                "n",
                "--channel",
                "email",
                "--tags",
                "x",
            ],
            input="not-an-email\n",
        )
        assert result.exit_code == 1
        assert "to_addr" in result.stdout


# ---------------------------------------------------------------------------
# patch / rm
# ---------------------------------------------------------------------------


class TestPatchAndRm:
    @patch("intellisource.cli.main.httpx")
    def test_patch_sends_body_with_provided_fields_only(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.patch.return_value = _mock_response(
            json_data={"id": "abc", "frequency": "daily"}
        )
        result = runner.invoke(
            app, ["subscriptions", "patch", "abc", "--frequency", "daily", "--json"]
        )
        assert result.exit_code == 0
        url = mock_httpx.patch.call_args.args[0]
        assert url.endswith("/api/v1/subscriptions/abc")
        body = mock_httpx.patch.call_args.kwargs["json"]
        assert body == {"frequency": "daily"}, "patch must omit unset fields"

    @patch("intellisource.cli.main.httpx")
    def test_patch_without_any_field_aborts(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(app, ["subscriptions", "patch", "abc"])
        assert result.exit_code == 2
        assert "Nothing to patch" in result.stdout
        mock_httpx.patch.assert_not_called()

    @patch("intellisource.cli.main.httpx")
    def test_rm_calls_delete_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.delete.return_value = _mock_response(status_code=204)
        result = runner.invoke(app, ["subscriptions", "rm", "abc"])
        assert result.exit_code == 0
        assert "Paused" in result.stdout
        url = mock_httpx.delete.call_args.args[0]
        assert url.endswith("/api/v1/subscriptions/abc")

    @patch("intellisource.cli.main.httpx")
    def test_rm_404_exits_with_code_1(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.delete.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["subscriptions", "rm", "missing"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


# ---------------------------------------------------------------------------
# reload / rollback
# ---------------------------------------------------------------------------


class TestReloadAndRollback:
    @patch("intellisource.cli.main.httpx")
    def test_reload_posts_to_reload_endpoint(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            json_data={"loaded_count": 3, "version": "5", "errors": []}
        )
        result = runner.invoke(app, ["subscriptions", "reload", "--json"])
        assert result.exit_code == 0
        url = mock_httpx.post.call_args.args[0]
        assert url.endswith("/api/v1/subscriptions/reload")
        body = json.loads(result.stdout.strip())
        assert body["version"] == "5"

    @patch("intellisource.cli.main.httpx")
    def test_rollback_posts_versioned_path(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            json_data={
                "rolled_back_to": "3",
                "config_count": 2,
                "subscription_names": ["a", "b"],
            }
        )
        result = runner.invoke(app, ["subscriptions", "rollback", "3", "--json"])
        assert result.exit_code == 0
        url = mock_httpx.post.call_args.args[0]
        assert url.endswith("/api/v1/subscriptions/config/rollback/3")

    @patch("intellisource.cli.main.httpx")
    def test_rollback_404_exits_with_code_1(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.post.return_value = _mock_response(
            status_code=404, json_data={"detail": "Version '99' not found"}
        )
        result = runner.invoke(app, ["subscriptions", "rollback", "99"])
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()


# ---------------------------------------------------------------------------
# show / patch-digest / versions / diff
# ---------------------------------------------------------------------------


class TestShow:
    @patch("intellisource.cli.main.httpx")
    def test_show_renders_detail_and_render_mode(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "id": "abc",
                "name": "d",
                "channel": "email",
                "frequency": "daily",
                "channel_config": {
                    "to_addr": "u@x.com",
                    "template": "daily-brief",
                    "template_config": {"render_mode": "llm-freeform"},
                },
            }
        )
        result = runner.invoke(app, ["subscriptions", "show", "abc"])
        assert result.exit_code == 0
        assert mock_httpx.get.call_args.args[0].endswith("/api/v1/subscriptions/abc")
        # vertical detail + the digest annotation block
        assert "render_mode (configured): llm-freeform" in result.stdout
        assert "downgrades to 'code'" in result.stdout

    @patch("intellisource.cli.main.httpx")
    def test_show_404_exits_1(self, mock_httpx: MagicMock, runner: CliRunner) -> None:
        mock_httpx.get.return_value = _mock_response(status_code=404)
        result = runner.invoke(app, ["subscriptions", "show", "missing"])
        assert result.exit_code == 1
        assert "Not found" in result.stdout


class TestPatchDigest:
    @patch("intellisource.cli.main.httpx")
    def test_patch_merges_render_mode_preserving_to_addr(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        # GET current config (has to_addr) then PATCH must keep it.
        mock_httpx.get.return_value = _mock_response(
            json_data={"id": "abc", "channel_config": {"to_addr": "keep@x.com"}}
        )
        mock_httpx.patch.return_value = _mock_response(json_data={"id": "abc"})
        result = runner.invoke(
            app,
            [
                "subscriptions",
                "patch",
                "abc",
                "--render-mode",
                "llm-freeform",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = mock_httpx.patch.call_args.kwargs["json"]
        cc = body["channel_config"]
        assert cc["to_addr"] == "keep@x.com", "merge must not wipe existing keys"
        assert cc["template_config"]["render_mode"] == "llm-freeform"

    @patch("intellisource.cli.main.httpx")
    def test_patch_invalid_render_mode_exits_2(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={"id": "abc", "channel_config": {"to_addr": "k@x.com"}}
        )
        result = runner.invoke(
            app, ["subscriptions", "patch", "abc", "--render-mode", "llm_freeform"]
        )
        assert result.exit_code == 2
        assert "render_mode must be one of" in result.stdout
        mock_httpx.patch.assert_not_called()

    @patch("intellisource.cli.main.httpx")
    def test_patch_digest_404_on_get_exits_1(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(status_code=404)
        result = runner.invoke(
            app, ["subscriptions", "patch", "missing", "--template", "daily-brief"]
        )
        assert result.exit_code == 1
        assert "Not found" in result.stdout


class TestVersionsAndDiff:
    @patch("intellisource.cli.main.httpx")
    def test_versions_lists_snapshots(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "versions": [
                    {"version": "2", "author": None, "config_count": 3},
                    {"version": "1", "author": "x", "config_count": 1},
                ]
            }
        )
        result = runner.invoke(app, ["subscriptions", "versions"])
        assert result.exit_code == 0
        assert (
            "/api/v1/subscriptions/config/versions" in mock_httpx.get.call_args.args[0]
        )
        assert "version" in result.stdout
        assert "config_count" in result.stdout

    @patch("intellisource.cli.main.httpx")
    def test_diff_renders_reload_preview(
        self, mock_httpx: MagicMock, runner: CliRunner
    ) -> None:
        mock_httpx.get.return_value = _mock_response(
            json_data={
                "yaml_only": ["fresh"],
                "db_only": ["gone"],
                "both": ["keep"],
                "db_only_action": "pause",
            }
        )
        result = runner.invoke(app, ["subscriptions", "diff"])
        assert result.exit_code == 0
        assert "reload will PAUSE" in result.stdout
        assert "fresh" in result.stdout
