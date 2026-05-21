"""Tests for T-091: reload_source_configs real implementation.

Covers:
  AC-3: reload_source_configs calls ConfigLoader.load_source_configs +
        ConfigValidator.validate + SourceRepository.bulk_upsert; returns
        real loaded_count (not hardcoded)
  AC-4: ConfigValidator.validate failure is caught; error appended to
        errors list; execution continues
  AC-5: SourceRepository.bulk_upsert is called exactly once with validated
        configs list
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.routers.sources import router

# ---------------------------------------------------------------------------
# App fixture for router-level tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI app with only the sources router."""
    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1")
    return _app


def _make_source_config(name: str = "test-source") -> MagicMock:
    """Return a MagicMock SourceConfig."""
    cfg = MagicMock()
    cfg.name = name
    return cfg


# ---------------------------------------------------------------------------
# AC-3: Real implementation — loaded_count reflects actual configs loaded
# ---------------------------------------------------------------------------


class TestReloadSourceConfigsHappyPath:
    """reload_source_configs returns real counts from ConfigLoader, not hardcoded 0."""

    async def test_reload_returns_real_loaded_count_for_two_configs(
        self, app: FastAPI
    ) -> None:
        """AC-3: loaded_count=2 when loader returns 2 + validator passes both."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        assert response.status_code == 200, (
            f"Expected 200 OK, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data.get("loaded_count") == 2, (
            f"Expected loaded_count=2, got {data.get('loaded_count')}. "
            "reload_source_configs must return real count, not hardcoded 0."
        )
        assert data.get("errors") == [], (
            f"Expected empty errors list, got {data.get('errors')}"
        )

    async def test_reload_returns_real_loaded_count_for_one_config(
        self, app: FastAPI
    ) -> None:
        """AC-3 / AC-5: loaded_count=1; bulk_upsert gets single validated."""
        config_a = _make_source_config("source-a")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        data = response.json()
        assert data.get("loaded_count") == 1, (
            f"Expected loaded_count=1, got {data.get('loaded_count')}"
        )

    async def test_reload_calls_load_source_configs(self, app: FastAPI) -> None:
        """AC-3: reload_source_configs calls ConfigLoader.load_source_configs()."""
        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/sources/reload", json={"config_name": None})

        mock_loader.load_source_configs.assert_called_once()

    async def test_reload_calls_validator_validate_per_config(
        self, app: FastAPI
    ) -> None:
        """AC-3: ConfigValidator.validate is called for each config from loader."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/sources/reload", json={"config_name": None})

        assert mock_validator.validate.call_count == 2, (
            f"Expected validate called 2 times (once per config), "
            f"got {mock_validator.validate.call_count}"
        )


# ---------------------------------------------------------------------------
# AC-4: ValidationError caught, appended to errors, processing continues
# ---------------------------------------------------------------------------


class TestReloadSourceConfigsValidationError:
    """When validator raises, error is captured; other configs continue."""

    async def test_validation_error_goes_to_errors_list(self, app: FastAPI) -> None:
        """AC-4: ValidationError from validator is caught and added to errors list."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        call_count = 0

        def _validate_side_effect(cfg: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate ValidationError for first config
                raise ValueError("invalid config: missing required field")
            return cfg

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=_validate_side_effect)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        errors = data.get("errors", [])
        assert len(errors) == 1, (
            f"Expected 1 error in errors list (for the failed config), got {errors}"
        )

    async def test_validation_error_does_not_stop_processing_remaining_configs(
        self, app: FastAPI
    ) -> None:
        """AC-4: After config_a validation failure, config_b is still processed."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        call_count = 0

        def _validate_side_effect(cfg: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("invalid config")
            return cfg

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=_validate_side_effect)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        data = response.json()
        # One config failed validation, one succeeded: loaded_count must be 1
        assert data.get("loaded_count") == 1, (
            f"Expected loaded_count=1 (2nd ok), got {data.get('loaded_count')}"
        )

    async def test_validation_error_response_includes_error_detail(
        self, app: FastAPI
    ) -> None:
        """AC-4: errors list entries contain file/error information."""
        config_a = _make_source_config("source-a")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(
            side_effect=ValueError("url field required")
        )
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        data = response.json()
        errors = data.get("errors", [])
        assert len(errors) == 1, f"Expected 1 error entry, got {errors}"
        # Each error entry should have some identifying key (error/message/detail)
        err = errors[0]
        assert isinstance(err, dict), f"Error entry must be a dict, got {type(err)}"
        has_error_info = any(k in err for k in ("error", "message", "detail", "reason"))
        assert has_error_info, (
            f"Error entry must carry an error/message/detail key, got: {err}"
        )

    async def test_all_configs_fail_validation_returns_zero_loaded_count(
        self, app: FastAPI
    ) -> None:
        """AC-4: All configs fail → loaded_count=0 + errors populated."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=ValueError("invalid"))
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/sources/reload", json={"config_name": None}
                )

        data = response.json()
        assert data.get("loaded_count") == 0, (
            f"Expected 0 when all configs fail, got {data.get('loaded_count')}"
        )
        assert len(data.get("errors", [])) == 2, (
            f"Expected 2 error entries, got {data.get('errors')}"
        )


# ---------------------------------------------------------------------------
# AC-5: SourceRepository.bulk_upsert called exactly once with validated configs
# ---------------------------------------------------------------------------


class TestReloadSourceConfigsBulkUpsert:
    """bulk_upsert is called exactly once after validation."""

    async def test_bulk_upsert_called_exactly_once(self, app: FastAPI) -> None:
        """AC-5: bulk_upsert called exactly once regardless of config count."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=lambda cfg: cfg)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/sources/reload", json={"config_name": None})

        mock_repo.bulk_upsert.assert_called_once()

    async def test_bulk_upsert_receives_validated_configs_list(
        self, app: FastAPI
    ) -> None:
        """AC-5: bulk_upsert called with the validated SourceConfig list."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")
        validated_a = MagicMock(name="validated_a")
        validated_b = MagicMock(name="validated_b")

        def _validate(cfg: Any) -> Any:
            if cfg is config_a:
                return validated_a
            return validated_b

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=_validate)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/sources/reload", json={"config_name": None})

        call_args = mock_repo.bulk_upsert.call_args
        # bulk_upsert must have been called with the two validated configs
        passed_configs = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("configs")
        )
        assert passed_configs is not None, (
            "bulk_upsert must receive configs as first arg"
        )
        assert len(passed_configs) == 2, (
            f"Expected bulk_upsert to get 2 configs, got {len(passed_configs)}"
        )

    async def test_bulk_upsert_excludes_failed_validation_configs(
        self, app: FastAPI
    ) -> None:
        """AC-5: bulk_upsert receives only successfully validated configs."""
        config_a = _make_source_config("source-a")
        config_b = _make_source_config("source-b")
        validated_b = MagicMock(name="validated_b")

        call_count = 0

        def _validate(cfg: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("invalid config_a")
            return validated_b

        mock_loader = MagicMock()
        mock_loader.load_source_configs = MagicMock(return_value=[config_a, config_b])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=_validate)
        mock_repo = MagicMock()
        mock_repo.bulk_upsert = AsyncMock()

        with (
            patch(
                "intellisource.api.routers.sources.ConfigLoader",
                return_value=mock_loader,
            ),
            patch(
                "intellisource.api.routers.sources.ConfigValidator",
                return_value=mock_validator,
            ),
            patch(
                "intellisource.api.routers.sources.SourceRepository",
                return_value=mock_repo,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post("/api/v1/sources/reload", json={"config_name": None})

        call_args = mock_repo.bulk_upsert.call_args
        passed_configs = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("configs")
        )
        assert passed_configs is not None, "bulk_upsert must receive configs argument"
        assert len(passed_configs) == 1, (
            f"Expected bulk_upsert to receive only 1 validated config "
            f"(config_a failed validation), got {len(passed_configs)}"
        )
        assert passed_configs[0] is validated_b, (
            "The single passed config must be the validated config_b"
        )
