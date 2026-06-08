"""Typed view over ``request.app.state`` and a startup registration guard.

``AppState`` documents the service handles installed by ``build_api_composition``
(plus ``db`` / ``missing_config`` installed by the lifespan before it). Reading
through ``get_app_state(request)`` gives mypy a typed handle instead of an
untyped ``getattr`` string lookup. ``validate_app_state`` runs at the end of
``build_api_composition`` so a forgotten or renamed registration fails the
process at startup rather than degrading silently to a per-request 503.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from intellisource.core.errors import CompositionError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

    from intellisource.agent.runner import AgentRunner
    from intellisource.composition.builders import PipelineLoader
    from intellisource.config.loader import ConfigVersionManager
    from intellisource.core.webhook_crypto import WeComCrypto
    from intellisource.distributor.wechat_cs_client import WeChatCustomerServiceClient
    from intellisource.distributor.wework_cs_client import WeWorkCustomerServiceClient
    from intellisource.llm.gateway import LLMGateway
    from intellisource.observability.health import HealthChecker
    from intellisource.observability.metrics import MetricsCollector
    from intellisource.observability.shared_metrics import RedisMetricStore
    from intellisource.storage.database import DatabaseManager


class AppState(Protocol):
    """Structural type of the service handles on ``app.state`` after startup.

    Handles whose value may legitimately be ``None`` (optional channels not
    configured via env) are typed ``X | None``; the rest are always present
    once ``build_api_composition`` has run and ``validate_app_state`` passed.
    """

    # Installed by the lifespan before build_api_composition.
    db: DatabaseManager
    missing_config: list[str]

    # Installed by build_api_composition.
    celery_app: Any
    llm_gateway: LLMGateway
    pipeline_loader: PipelineLoader
    agent_runner: AgentRunner
    background_tasks: set[Any]
    health_checker: HealthChecker
    metrics_collector: MetricsCollector
    shared_metrics: RedisMetricStore
    config_version_manager: ConfigVersionManager
    wechat_webhook_token: str
    wecom_crypto: WeComCrypto | None
    wechat_cs_messenger: WeChatCustomerServiceClient | None
    wework_cs_messenger: WeWorkCustomerServiceClient | None


# Keys that build_api_composition is responsible for installing. A missing key
# here means a registration drift (renamed/forgotten write) that would otherwise
# surface only as a silent read-side ``getattr(..., None)`` → 503.
REQUIRED_APP_STATE_KEYS: tuple[str, ...] = (
    "celery_app",
    "llm_gateway",
    "pipeline_loader",
    "agent_runner",
    "background_tasks",
    "health_checker",
    "metrics_collector",
    "shared_metrics",
    "config_version_manager",
    "wechat_webhook_token",
    "wecom_crypto",
    "wechat_cs_messenger",
    "wework_cs_messenger",
)


def get_app_state(request: Request) -> AppState:
    """Return ``request.app.state`` typed as :class:`AppState`."""
    return cast("AppState", request.app.state)


def validate_app_state(app: FastAPI) -> None:
    """Fail loudly if build_api_composition skipped any required registration."""
    missing = [key for key in REQUIRED_APP_STATE_KEYS if not hasattr(app.state, key)]
    if missing:
        raise CompositionError(
            "build_api_composition did not install required app.state keys: "
            + ", ".join(missing)
        )
