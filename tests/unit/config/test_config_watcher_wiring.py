"""Tests for T-091: ConfigWatcher lifespan wiring.

Covers:
  AC-1: _lifespan instantiates ConfigWatcher and launches background task
  AC-2: on_config_change flows through ConfigLoader/Validator/Repository.upsert
  AC-6: app.state.config_watcher is non-None after lifespan startup
  AC-7: yaml.safe_load-only security guard in config/ directory
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from source_scan import find_regex_in_tree

from intellisource.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_watcher() -> MagicMock:
    """Return a MagicMock ConfigWatcher with async start/stop."""
    watcher = MagicMock()
    watcher.start = AsyncMock()
    watcher.stop = AsyncMock()
    return watcher


# ---------------------------------------------------------------------------
# AC-1: _lifespan startup instantiates ConfigWatcher with correct kwargs
#       and calls watcher.stop() on shutdown
# ---------------------------------------------------------------------------


class TestLifespanConfigWatcherInstantiation:
    """_lifespan creates ConfigWatcher with the right args and stops it on exit."""

    async def test_startup_instantiates_config_watcher_with_source_config_dir(
        self,
    ) -> None:
        """AC-1: ConfigWatcher is constructed with config_dir from settings."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ) as mock_watcher_cls,
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

        # ConfigWatcher must have been instantiated
        mock_watcher_cls.assert_called_once()
        call_kwargs = mock_watcher_cls.call_args

        # config_dir kwarg must be set (from settings.SOURCE_CONFIG_DIR)
        config_dir_value = call_kwargs.kwargs.get(
            "config_dir", call_kwargs.args[0] if call_kwargs.args else None
        )
        assert isinstance(config_dir_value, str) and config_dir_value, (
            "ConfigWatcher must be called with a non-empty config_dir string"
        )

    async def test_startup_passes_callback_to_config_watcher(self) -> None:
        """AC-1: ConfigWatcher is constructed with a callable callback kwarg."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ) as mock_watcher_cls,
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

        call_kwargs = mock_watcher_cls.call_args
        kwargs = call_kwargs.kwargs
        args = call_kwargs.args
        callback = kwargs.get("callback")
        if callback is None and len(args) >= 2:
            callback = args[1]
        assert callable(callback), (
            "ConfigWatcher must be called with a callable callback argument"
        )

    async def test_startup_creates_background_task_for_watcher(self) -> None:
        """AC-1: asyncio.create_task is called to start watcher.start/run()."""
        import asyncio

        mock_watcher_instance = _make_mock_watcher()
        # run() is the method described in AC; start() exists in current implementation
        mock_watcher_instance.run = AsyncMock()

        tasks_created: list[Any] = []
        original_create_task = asyncio.create_task

        def _tracking_create_task(coro: Any, **kw: Any) -> Any:
            t = original_create_task(coro, **kw)
            tasks_created.append(t)
            return t

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ),
            patch(
                "intellisource.main.asyncio.create_task",
                side_effect=_tracking_create_task,
            ),
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

        # asyncio.create_task must be called once for the watcher.
        assert len(tasks_created) == 1, (
            f"create_task must be called once for the watcher, got {len(tasks_created)}"
        )
        assert mock_watcher_instance.start.called, (
            "watcher.start() must be called during lifespan startup"
        )

    async def test_shutdown_calls_watcher_stop(self) -> None:
        """AC-1: watcher.stop() is called during lifespan shutdown."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ),
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                pass

        mock_watcher_instance.stop.assert_called_once()

    async def test_shutdown_calls_watcher_stop_even_on_error(self) -> None:
        """AC-1: watcher.stop() is called even when the app body raises an exception."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ),
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            try:
                async with lifespan(app):
                    raise RuntimeError("simulated app error")
            except RuntimeError:
                pass

        mock_watcher_instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# AC-2: on_config_change callback flows through loader → validator → repo.upsert
# ---------------------------------------------------------------------------


def _make_mock_db_manager() -> MagicMock:
    """MagicMock DatabaseManager with async ctx-manager get_session()."""
    mock_session = MagicMock()
    mock_db = MagicMock()
    mock_db.get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_db.get_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_db


class TestOnConfigChangeCallback:
    """on_config_change(path) calls ConfigLoader.load_file → ConfigValidator.validate
    → SourceRepository.upsert in order."""

    async def test_callback_calls_loader_load_file(self) -> None:
        """AC-2: on_config_change calls ConfigLoader.load_file(path)."""
        import intellisource.main as main_module

        # on_config_change must exist as a function/coroutine in main
        assert hasattr(main_module, "on_config_change"), (
            "main.py must define on_config_change function"
        )

        mock_configs = [MagicMock()]
        mock_loader = MagicMock()
        mock_loader.load_file = MagicMock(return_value=mock_configs)
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(return_value=mock_configs[0])
        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock()
        mock_db = _make_mock_db_manager()

        with (
            patch("intellisource.main.ConfigLoader", return_value=mock_loader),
            patch("intellisource.main.ConfigValidator", return_value=mock_validator),
            patch("intellisource.main.SourceRepository", return_value=mock_repo),
            patch("intellisource.main._db_manager", mock_db),
        ):
            on_change = main_module.on_config_change
            await on_change("/etc/sources/arxiv.yaml")

        mock_loader.load_file.assert_called_once_with("/etc/sources/arxiv.yaml")

    async def test_callback_calls_validator_validate(self) -> None:
        """AC-2: on_config_change calls ConfigValidator.validate per config."""
        import intellisource.main as main_module

        assert hasattr(main_module, "on_config_change"), (
            "main.py must define on_config_change function"
        )

        mock_config = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load_file = MagicMock(return_value=[mock_config])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(return_value=mock_config)
        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock()
        mock_db = _make_mock_db_manager()

        with (
            patch("intellisource.main.ConfigLoader", return_value=mock_loader),
            patch("intellisource.main.ConfigValidator", return_value=mock_validator),
            patch("intellisource.main.SourceRepository", return_value=mock_repo),
            patch("intellisource.main._db_manager", mock_db),
        ):
            on_change = main_module.on_config_change
            await on_change("/etc/sources/arxiv.yaml")

        mock_validator.validate.assert_called()

    async def test_callback_calls_repo_upsert(self) -> None:
        """AC-2: on_config_change calls Repository.upsert with validated config."""
        import intellisource.main as main_module

        assert hasattr(main_module, "on_config_change"), (
            "main.py must define on_config_change function"
        )

        mock_config = MagicMock()
        validated_config = MagicMock()
        mock_loader = MagicMock()
        mock_loader.load_file = MagicMock(return_value=[mock_config])
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(return_value=validated_config)
        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock()
        mock_db = _make_mock_db_manager()

        with (
            patch("intellisource.main.ConfigLoader", return_value=mock_loader),
            patch("intellisource.main.ConfigValidator", return_value=mock_validator),
            patch("intellisource.main.SourceRepository", return_value=mock_repo),
            patch("intellisource.main._db_manager", mock_db),
        ):
            on_change = main_module.on_config_change
            await on_change("/etc/sources/arxiv.yaml")

        mock_repo.upsert.assert_called_once()

    async def test_callback_call_order_loader_then_validator_then_repo(self) -> None:
        """AC-2: call order is ConfigLoader.load_file → ConfigValidator.validate →
        SourceRepository.upsert."""
        import intellisource.main as main_module

        assert hasattr(main_module, "on_config_change"), (
            "main.py must define on_config_change function"
        )

        call_order: list[str] = []
        mock_config = MagicMock()
        validated_config = MagicMock()

        def _load_file(path: str) -> list[MagicMock]:
            call_order.append("load_file")
            return [mock_config]

        def _validate(cfg: Any) -> MagicMock:
            call_order.append("validate")
            return validated_config

        async def _upsert(cfg: Any) -> None:
            call_order.append("upsert")

        mock_loader = MagicMock()
        mock_loader.load_file = MagicMock(side_effect=_load_file)
        mock_validator = MagicMock()
        mock_validator.validate = MagicMock(side_effect=_validate)
        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock(side_effect=_upsert)
        mock_db = _make_mock_db_manager()

        with (
            patch("intellisource.main.ConfigLoader", return_value=mock_loader),
            patch("intellisource.main.ConfigValidator", return_value=mock_validator),
            patch("intellisource.main.SourceRepository", return_value=mock_repo),
            patch("intellisource.main._db_manager", mock_db),
        ):
            on_change = main_module.on_config_change
            await on_change("/etc/sources/arxiv.yaml")

        assert call_order == ["load_file", "validate", "upsert"], (
            f"Expected call order load_file→validate→upsert, got: {call_order}"
        )


# ---------------------------------------------------------------------------
# AC-6: app.state.config_watcher is set and non-None after startup
# ---------------------------------------------------------------------------


class TestLifespanConfigWatcherAppState:
    """app.state.config_watcher is set to the ConfigWatcher instance after startup."""

    async def test_app_state_config_watcher_is_not_none_after_startup(self) -> None:
        """AC-6: After lifespan startup, app.state.config_watcher is non-None."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ),
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert hasattr(app.state, "config_watcher"), (
                    "app.state.config_watcher must be set during lifespan startup"
                )
                assert app.state.config_watcher is mock_watcher_instance, (
                    "app.state.config_watcher must be the constructed ConfigWatcher"
                )

    async def test_app_state_config_watcher_is_the_watcher_instance(self) -> None:
        """AC-6: app.state.config_watcher is the constructed ConfigWatcher."""
        mock_watcher_instance = _make_mock_watcher()

        with (
            patch("intellisource.main.DatabaseManager") as _mock_db_cls,
            patch("intellisource.main.aioredis") as _mock_aioredis,
            patch(
                "intellisource.main.ConfigWatcher",
                return_value=mock_watcher_instance,
            ),
        ):
            _mock_db_cls.return_value.close = AsyncMock()
            _mock_aioredis.from_url = AsyncMock()

            app = create_app()
            lifespan = app.router.lifespan_context

            async with lifespan(app):
                assert app.state.config_watcher is mock_watcher_instance, (
                    "app.state.config_watcher must be the constructor return value"
                )


# ---------------------------------------------------------------------------
# AC-7 (security): yaml.safe_load-only guard in config/ directory
# ---------------------------------------------------------------------------


class TestYamlSafeLoadOnlyInConfigDir:
    """ConfigLoader.load_file uses yaml.safe_load; no unsafe yaml.load variants."""

    def test_no_unsafe_yaml_calls_in_config_directory(self) -> None:
        """AC-7: no yaml.load/full_load/unsafe_load in src/intellisource/config/
        except those explicitly passing Loader=yaml.SafeLoader."""
        config_dir = _REPO_ROOT / "src" / "intellisource" / "config"
        lines = find_regex_in_tree(config_dir, r"yaml\.(load|full_load|unsafe_load)\(")
        unsafe_lines = [line for line in lines if "Loader=yaml.SafeLoader" not in line]
        assert unsafe_lines == [], (
            "Unsafe yaml calls in src/intellisource/config/ "
            "(missing Loader=yaml.SafeLoader):\n" + "\n".join(unsafe_lines)
        )

    def test_no_unsafe_yaml_load_without_safe_loader(self) -> None:
        """AC-7: no yaml.load( without SafeLoader anywhere in config/."""
        config_dir = _REPO_ROOT / "src" / "intellisource" / "config"
        lines = find_regex_in_tree(config_dir, r"yaml\.(load|full_load|unsafe_load)\(")
        unsafe_lines = [line for line in lines if "Loader=yaml.SafeLoader" not in line]
        assert unsafe_lines == [], (
            "Unsafe yaml calls found — must use yaml.safe_load() exclusively:\n"
            + "\n".join(unsafe_lines)
        )
