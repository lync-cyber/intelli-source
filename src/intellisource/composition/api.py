"""API-side composition entry point.

``build_api_composition`` is called from ``intellisource.main._lifespan``. It
assembles the same dependency graph as the Worker and installs the service
handles onto ``app.state`` for request handlers and middleware to consume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intellisource.composition.app_state import validate_app_state
from intellisource.composition.builders import (
    _maybe_build_http_client,
    build_pipeline_loader,
)
from intellisource.composition.deps import _build_deps_bundle, _install_agent_runner
from intellisource.core.settings import get_settings
from intellisource.observability.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

    from intellisource.storage.database import DatabaseManager


def build_api_composition(
    app: FastAPI,
    db_manager: DatabaseManager,
    redis_client: Any,
) -> None:
    """Wire up the API-side composition graph and install it on `app.state`.

    Called from `intellisource.main._lifespan`. Writes the assembled
    `celery_app` / `llm_gateway` / `pipeline_loader` / `agent_runner` onto
    `app.state` so request handlers and middleware can reach them via
    `request.app.state.<attr>`.

    The API process and Worker process share the SAME Celery() instance via
    the module-level `intellisource.scheduler.celery_app.celery_app` — this
    is what closes CR-012 (dual-singleton).
    """
    # Trigger @celery_app.task(name="run_pipeline") registration so the API
    # process can `send_task("run_pipeline", ...)` and hit the same task
    # definition the Worker consumes.
    import intellisource.scheduler.tasks  # noqa: F401  registers run_pipeline
    from intellisource.scheduler.celery_app import celery_app as module_celery_app

    app.state.celery_app = module_celery_app
    _api_celery_app = module_celery_app

    # DatabaseManager exposes get_session() (an async context manager) but
    # not a sessionmaker. Agent tools invoke `tool_deps.session_factory()`
    # then `async with` on the result, so we adapt get_session into a
    # callable returning the existing context manager.
    session_factory = _DatabaseManagerSessionFactory(db_manager)

    bundle = _build_deps_bundle(
        session_factory, redis_client, celery_app=_api_celery_app
    )
    agent_runner = _install_agent_runner(session_factory, bundle)
    pipeline_loader = build_pipeline_loader(session_factory)

    app.state.llm_gateway = bundle.llm_gateway
    app.state.pipeline_loader = pipeline_loader
    app.state.agent_runner = agent_runner

    _install_webhook_state(app, redis_client=redis_client)
    app.state.background_tasks = set()
    _install_observability_state(app, db_manager=db_manager, redis_client=redis_client)

    # Fail loudly now if any required handle was missed, rather than letting a
    # router's getattr(..., None) degrade to a silent 503 at request time.
    validate_app_state(app)


def _install_observability_state(
    app: FastAPI, *, db_manager: DatabaseManager, redis_client: Any
) -> None:
    """Wire health_checker / metrics_collector / config_version_manager state.

    AC-T099-5 — replaces the placeholder stubs in `api/routers/system.py` with
    a real `HealthChecker` (checks: db, redis, celery), the singleton
    `MetricsCollector`, and a fresh `ConfigVersionManager` snapshot store
    consumed by `main.on_config_change`.
    """
    from intellisource.config.loader import ConfigVersionManager
    from intellisource.observability.health import HealthChecker
    from intellisource.observability.metrics import MetricsCollector

    metrics_collector_instance = MetricsCollector.get_instance()
    checker = HealthChecker(metrics_collector=metrics_collector_instance)

    async def _check_db() -> bool:
        # Exceptions propagate so HealthChecker can capture them as
        # ``details[db].last_error`` — silent ``except: return False`` here
        # would lose the diagnostic message operators need.
        async with db_manager.get_session() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
        return True

    async def _check_redis() -> bool:
        await redis_client.ping()
        return True

    async def _check_celery() -> bool:
        import asyncio as _asyncio

        celery_app = getattr(app.state, "celery_app", None)
        if celery_app is None:
            return False
        # `control.ping` is a sync broker round-trip; offload to a worker
        # thread so the /health coroutine never blocks the event loop on a
        # stuck broker. Exceptions propagate to HealthChecker for error
        # capture; an empty reply list means no workers up — degraded, not
        # an error.
        replies = await _asyncio.to_thread(celery_app.control.ping, timeout=0.5)
        return bool(replies)

    checker.register_check("db", _check_db)
    checker.register_check("redis", _check_redis)
    checker.register_check("celery", _check_celery)
    app.state.health_checker = checker

    app.state.metrics_collector = metrics_collector_instance

    # Cross-process metric sink: the API endpoint reads worker-recorded
    # families (celery_*) back from the shared Redis store at scrape time.
    from intellisource.observability.shared_metrics import get_shared_metric_store

    app.state.shared_metrics = get_shared_metric_store()
    from intellisource.config.models import SourceConfig

    app.state.config_version_manager = ConfigVersionManager(
        table_name="config_versions",
        config_cls=SourceConfig,
    )


def _install_webhook_state(app: FastAPI, *, redis_client: Any) -> None:
    """Wire webhook tokens + CS messenger clients onto `app.state`.

    Env presence rules:

    - `IS_WECHAT_WEBHOOK_TOKEN` / `IS_WEWORK_WEBHOOK_TOKEN` — when missing,
      the corresponding token state is set to "" and the router's signature
      check rejects every callback with 403 (no silent bypass). A startup
      warning is logged so operators notice the gap.
    - `IS_WECHAT_APP_ID` + `IS_WECHAT_APP_SECRET` — when **partially** set,
      `WeChatCustomerServiceClient.from_env` raises ValueError and that
      propagates out of `_install_webhook_state` to crash startup loud,
      matching the sprint-9 locked credential policy. When fully unset,
      construction is skipped and `wechat_cs_messenger` stays None.
    - `IS_WEWORK_CORP_ID` + `IS_WEWORK_CORP_SECRET` + `IS_WEWORK_AGENT_ID`
      follow the same partial-set hard-fail / fully-unset skip rule.
    """

    from intellisource.distributor.wechat_cs_client import (
        WeChatCustomerServiceClient,
    )
    from intellisource.distributor.wework_cs_client import (
        WeWorkCustomerServiceClient,
    )

    logger = get_logger(__name__)

    settings = get_settings()
    wechat_token = settings.wechat_webhook_token
    wework_token = settings.wework_webhook_token
    app.state.wechat_webhook_token = wechat_token
    app.state.wework_webhook_token = wework_token

    _wecom_token = settings.wecom_token
    _wecom_aes_key = settings.wecom_encoding_aes_key
    _wecom_corp_id = settings.wecom_corp_id
    if _wecom_token and _wecom_aes_key and _wecom_corp_id:
        from intellisource.core.webhook_crypto import WeComCrypto

        app.state.wecom_crypto = WeComCrypto(
            token=_wecom_token,
            encoding_aes_key=_wecom_aes_key,
            corp_id=_wecom_corp_id,
        )
    else:
        app.state.wecom_crypto = None
        if _wecom_token or _wecom_aes_key or _wecom_corp_id:
            logger.warning(
                "IS_WECOM_TOKEN / IS_WECOM_ENCODING_AES_KEY / IS_WECOM_CORP_ID"
                " are partially set — WeWork AES decryption disabled (503)"
            )

    http_client = _maybe_build_http_client()

    wechat_app_id_set = bool(settings.wechat_app_id)
    wechat_secret_set = bool(settings.wechat_app_secret)
    if wechat_app_id_set or wechat_secret_set:
        # Partial-set → from_env raises and we let it propagate (hard fail).
        app.state.wechat_cs_messenger = WeChatCustomerServiceClient.from_env(
            redis_client=redis_client, http_client=http_client
        )
    else:
        app.state.wechat_cs_messenger = None

    wework_keys = (
        bool(settings.wework_corp_id),
        bool(settings.wework_corp_secret),
        bool(settings.wework_agent_id),
    )
    if any(wework_keys):
        # Partial-set → from_env raises and we let it propagate (hard fail).
        app.state.wework_cs_messenger = WeWorkCustomerServiceClient.from_env(
            redis_client=redis_client, http_client=http_client
        )
    else:
        app.state.wework_cs_messenger = None

    if not wechat_token and not wework_token:
        logger.warning(
            "Both IS_WECHAT_WEBHOOK_TOKEN and IS_WEWORK_WEBHOOK_TOKEN are unset"
            " — /api/v1/webhooks/{wechat,wework} will reject all callbacks (403)"
        )


class _DatabaseManagerSessionFactory:
    """Adapter that exposes `DatabaseManager.get_session()` as a callable.

    Tool execute functions invoke `tool_deps.session_factory()` and then
    `async with` on the result. `DatabaseManager.get_session()` is already
    an async context manager, so we just forward the call.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def __call__(self) -> Any:
        return self._db_manager.get_session()
