"""AC-11: Celery app singleton unified between API and Worker.

- main.init_celery() and main.shutdown_celery() do not exist
- main._lifespan binds app.state.celery_app to the module singleton in
  intellisource.scheduler.celery_app
- API and Worker share the SAME Celery() instance (same task registry, conf)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# AC-11: app.state.celery_app is scheduler.celery_app.celery_app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_state_celery_app_is_module_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-11: After create_app() lifespan runs, app.state.celery_app IS the
    module-level singleton from scheduler.celery_app.

    Current main: app.state.celery_app is a fresh Celery() built by
    main.init_celery() — distinct object → 'is' comparison fails.
    """
    monkeypatch.setenv("IS_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("IS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    # Patch external IO that lifespan touches (Redis from_url + config watcher start).
    # NB: main.py:59 does `await aioredis.from_url(...)`, so the patched callable
    # must return an awaitable. Use AsyncMock so its return value is awaitable.
    with (
        patch(
            "intellisource.main.aioredis.from_url",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch(
            "intellisource.main.ConfigWatcher",
            autospec=True,
        ) as mock_watcher_cls,
        patch(
            "intellisource.main.DatabaseManager",
            autospec=True,
        ) as mock_db_cls,
    ):
        mock_watcher = mock_watcher_cls.return_value
        mock_watcher.start = MagicMock(return_value=_noop_coro())
        mock_watcher.stop = MagicMock(return_value=_noop_coro())
        mock_db = mock_db_cls.return_value
        mock_db.close = MagicMock(return_value=_noop_coro())

        from intellisource.main import create_app
        from intellisource.scheduler.celery_app import celery_app as module_celery_app

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Trigger lifespan by issuing any request.
            resp = await ac.get("/health")
            assert resp.status_code == 200

            celery_on_state = getattr(app.state, "celery_app", None)
            assert celery_on_state is not None, "app.state.celery_app not set"
            assert celery_on_state is module_celery_app, (
                f"AC-11: app.state.celery_app must BE the scheduler.celery_app module "
                f"singleton (dual-singleton fix); got distinct objects: "
                f"id(state)={id(celery_on_state)} vs id(module)={id(module_celery_app)}"
            )


def test_main_does_not_define_init_celery() -> None:
    """AC-11 / AC-9 corollary: main.init_celery() does not exist."""
    import intellisource.main as main_mod

    assert not hasattr(main_mod, "init_celery"), (
        "AC-9: main.init_celery still exists; the dual-Celery-singleton bug "
        "requires it be removed"
    )


def test_main_does_not_define_shutdown_celery() -> None:
    """AC-11 / AC-9 corollary: main.shutdown_celery() does not exist."""
    import intellisource.main as main_mod

    assert not hasattr(main_mod, "shutdown_celery"), (
        "AC-9: main.shutdown_celery still exists; the dual-Celery-singleton "
        "bug requires it be removed"
    )


def test_run_pipeline_task_registered_on_module_singleton() -> None:
    """AC-11: 'run_pipeline' task is registered on the module-level celery_app.

    Side effect of `import intellisource.scheduler.tasks` triggering the
    @celery_app.task(name="run_pipeline") decorator. Confirms API process can
    send_task("run_pipeline") and reach the SAME task definition the worker
    consumes.
    """
    import intellisource.scheduler.tasks  # noqa: F401  trigger decorator
    from intellisource.scheduler.celery_app import celery_app

    assert "run_pipeline" in celery_app.tasks, (
        "AC-11: 'run_pipeline' is not registered on the module-level celery_app; "
        f"registered tasks: {sorted(celery_app.tasks.keys())[:10]}..."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_coro() -> None:
    return None
