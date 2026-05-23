"""Unit tests verifying that webhook routes are registered in create_app() (AC-6).

AC-6: main.create_app() registers webhooks.router under /api/v1, so
      OpenAPI schema contains both /api/v1/webhooks/wechat and
      /api/v1/webhooks/wework.
"""

from __future__ import annotations


class TestWebhookRouterRegistered:
    """AC-6: Webhook router included in create_app() OpenAPI schema."""

    def test_wechat_webhook_route_in_openapi(self) -> None:
        """OpenAPI schema paths include /api/v1/webhooks/wechat."""
        from intellisource.main import create_app

        app = create_app()
        openapi = app.openapi()
        paths = openapi.get("paths", {})
        wechat_path = "/api/v1/webhooks/wechat"
        assert wechat_path in paths, (
            f"Expected '{wechat_path}' in OpenAPI paths, found: {list(paths.keys())}"
        )

    def test_wework_webhook_route_in_openapi(self) -> None:
        """OpenAPI schema paths include /api/v1/webhooks/wework."""
        from intellisource.main import create_app

        app = create_app()
        openapi = app.openapi()
        paths = openapi.get("paths", {})
        wework_path = "/api/v1/webhooks/wework"
        assert wework_path in paths, (
            f"Expected '{wework_path}' in OpenAPI paths, found: {list(paths.keys())}"
        )

    def test_wechat_route_has_get_method(self) -> None:
        """GET /api/v1/webhooks/wechat (URL verify) is present in OpenAPI."""
        from intellisource.main import create_app

        app = create_app()
        openapi = app.openapi()
        paths = openapi.get("paths", {})
        wechat_entry = paths.get("/api/v1/webhooks/wechat", {})
        assert "get" in wechat_entry, (
            "GET method missing from /api/v1/webhooks/wechat — "
            "needed for WeChat URL verification handshake."
        )

    def test_wechat_route_has_post_method(self) -> None:
        """POST /api/v1/webhooks/wechat (message callback) is present in OpenAPI."""
        from intellisource.main import create_app

        app = create_app()
        openapi = app.openapi()
        paths = openapi.get("paths", {})
        wechat_entry = paths.get("/api/v1/webhooks/wechat", {})
        assert "post" in wechat_entry, (
            "POST method missing from /api/v1/webhooks/wechat — "
            "needed for incoming WeChat message callbacks."
        )

    def test_wework_route_has_post_method(self) -> None:
        """POST /api/v1/webhooks/wework is present in OpenAPI."""
        from intellisource.main import create_app

        app = create_app()
        openapi = app.openapi()
        paths = openapi.get("paths", {})
        wework_entry = paths.get("/api/v1/webhooks/wework", {})
        assert "post" in wework_entry, (
            "POST method missing from /api/v1/webhooks/wework — "
            "needed for incoming WeWork message callbacks."
        )
