"""Tests for the typed AppState view and startup registration guard (G5-4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from intellisource.composition.app_state import (
    REQUIRED_APP_STATE_KEYS,
    get_app_state,
    validate_app_state,
)
from intellisource.core.errors import CompositionError


def _app_with_keys(keys: tuple[str, ...]) -> MagicMock:
    """Return a stand-in FastAPI app whose state carries exactly *keys*."""
    app = MagicMock()
    app.state = SimpleNamespace(**{key: object() for key in keys})
    return app


class TestValidateAppState:
    def test_passes_when_all_required_keys_present(self) -> None:
        app = _app_with_keys(REQUIRED_APP_STATE_KEYS)
        validate_app_state(app)  # must not raise

    def test_raises_composition_error_listing_missing_keys(self) -> None:
        present = REQUIRED_APP_STATE_KEYS[:-2]
        missing = REQUIRED_APP_STATE_KEYS[-2:]
        app = _app_with_keys(present)

        with pytest.raises(CompositionError) as exc_info:
            validate_app_state(app)

        message = str(exc_info.value)
        for key in missing:
            assert key in message, f"missing key {key!r} must be named in {message!r}"

    def test_required_keys_cover_agent_runner_and_gateway(self) -> None:
        # These two are the handles most read sites depend on; a drift here is
        # exactly the silent-503 failure validate_app_state exists to catch.
        assert "agent_runner" in REQUIRED_APP_STATE_KEYS
        assert "llm_gateway" in REQUIRED_APP_STATE_KEYS


class TestGetAppState:
    def test_returns_the_underlying_request_state(self) -> None:
        sentinel_state = SimpleNamespace(db="db-handle")
        request = MagicMock()
        request.app.state = sentinel_state

        result = get_app_state(request)

        assert result is sentinel_state
        assert result.db == "db-handle"
