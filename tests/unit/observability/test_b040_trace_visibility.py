"""trace_id must be visible on real log lines (worker + api).

The walkthrough's ``grep trace_id=<uuid>`` found zero hits even though
propagation worked: the worker let Celery hijack the root logger (clobbering
the TraceIdFormatter) and neither hot path emitted a business log line that the
formatter could decorate. These tests pin the two carrier lines and the hijack
flag so the grep-based regression has something to match.
"""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from intellisource.api.middleware import TracingMiddleware
from intellisource.observability.logging import TraceIdFormatter
from intellisource.observability.trace_context import TRACE_HEADER_KEY


def _capture_logger(name: str) -> tuple[io.StringIO, logging.Handler]:
    """Attach a TraceIdFormatter-backed handler to *name*; return (buffer, handler)."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.INFO)
    handler.setFormatter(TraceIdFormatter())
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return buffer, handler


# ===========================================================================
# Worker side: Celery must NOT hijack the root logger
# ===========================================================================


def test_celery_does_not_hijack_root_logger() -> None:
    """worker_hijack_root_logger=False lets setup_logging's formatter survive."""
    from intellisource.scheduler.celery_app import celery_app

    assert celery_app.conf.worker_hijack_root_logger is False


def test_celery_does_not_redirect_stdouts() -> None:
    """worker_redirect_stdouts=False keeps sys.stderr real so setup_logging's
    handler is not bound to Celery's LoggingProxy (which swallows the lines)."""
    from intellisource.scheduler.celery_app import celery_app

    assert celery_app.conf.worker_redirect_stdouts is False


def test_prerun_emits_log_line_carrying_trace_id() -> None:
    """signals._on_task_prerun emits an INFO line decorated with the trace_id."""
    from intellisource.scheduler.signals import _on_task_prerun

    buffer, handler = _capture_logger("intellisource.scheduler.signals")
    try:
        task = SimpleNamespace(
            request=SimpleNamespace(headers={TRACE_HEADER_KEY: "trace-worker-xyz"}),
            name="run_pipeline",
        )
        _on_task_prerun(sender=task, task_id="task-1")
    finally:
        logging.getLogger("intellisource.scheduler.signals").removeHandler(handler)

    output = buffer.getvalue()
    assert "trace_id=trace-worker-xyz" in output, output
    assert output.strip(), "prerun must emit at least one log line"


# ===========================================================================
# API side: inbound request emits a trace_id-carrying line
# ===========================================================================


def _create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    app.add_middleware(TracingMiddleware)
    return app


@pytest.mark.asyncio
async def test_tracing_middleware_emits_inbound_log_with_trace_id() -> None:
    """TracingMiddleware emits an inbound INFO line carrying the trace_id."""
    buffer, handler = _capture_logger("intellisource.api.middleware")
    incoming = "trace-api-abc-123"
    try:
        app = _create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/ping", headers={"X-Trace-ID": incoming})
    finally:
        logging.getLogger("intellisource.api.middleware").removeHandler(handler)

    assert resp.status_code == 200
    output = buffer.getvalue()
    assert f"trace_id={incoming}" in output, output


def test_traceid_formatter_renders_bound_value() -> None:
    """Sanity: TraceIdFormatter renders the bound contextvar (not '-')."""
    from intellisource.observability.trace_context import set_trace_id

    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    token = set_trace_id("trace-render-1")
    try:
        rendered = TraceIdFormatter().format(record)
    finally:
        from intellisource.observability.trace_context import reset_trace_id

        reset_trace_id(token)
    assert "trace_id=trace-render-1" in rendered


# ===========================================================================
# Worker bootstrap: logging must be configured before the composition guard
# ===========================================================================


def test_worker_init_configures_logging_even_when_already_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker_init_handler must call setup_logging() before the _celery_tasks
    idempotency guard. A forked prefork child inherits a non-None _celery_tasks
    and short-circuits; if setup_logging ran after the guard, that child would
    keep an unconfigured root logger and (with hijack=False) drop every INFO
    line — exactly the trace_id= visibility gap this guards against.
    """
    import intellisource.scheduler.boot as boot_mod

    calls: list[str] = []
    monkeypatch.setattr(boot_mod, "setup_logging", lambda: calls.append("setup"))
    # Simulate a child that inherited an already-built composition.
    monkeypatch.setattr(boot_mod, "_celery_tasks", object())

    def _must_not_run() -> object:
        raise AssertionError("composition must not rebuild when the guard trips")

    monkeypatch.setattr(boot_mod, "init_worker_session_factory", _must_not_run)

    boot_mod.worker_init_handler(sender=object())

    assert calls == ["setup"], "setup_logging must run even when _celery_tasks is set"
