"""Tests for api.deps dependency injection helpers.

Covers:
- require_api_key() validation logic
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from intellisource.api.deps import require_api_key

# ---------------------------------------------------------------------------
# Tests: require_api_key
# ---------------------------------------------------------------------------


class TestRequireApiKey:
    """API key validation via IS_API_KEY env var."""

    def test_valid_key_accepted(self) -> None:
        with patch.dict(os.environ, {"IS_API_KEY": "secret-key-123"}):
            result = require_api_key("secret-key-123")
            assert result == "secret-key-123"

    def test_invalid_key_rejected(self) -> None:
        with patch.dict(os.environ, {"IS_API_KEY": "secret-key-123"}):
            with pytest.raises(HTTPException) as exc_info:
                require_api_key("wrong-key")
            assert exc_info.value.status_code == 401

    def test_missing_key_rejected(self) -> None:
        with patch.dict(os.environ, {"IS_API_KEY": "secret-key-123"}):
            with pytest.raises(HTTPException) as exc_info:
                require_api_key("")
            assert exc_info.value.status_code == 401

    def test_no_env_var_allows_any_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # When IS_API_KEY is not set, any key is accepted
            result = require_api_key("any-key")
            assert result == "any-key"

    def test_empty_env_var_allows_any_key(self) -> None:
        with patch.dict(os.environ, {"IS_API_KEY": ""}):
            result = require_api_key("any-key")
            assert result == "any-key"
