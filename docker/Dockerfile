# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder — install runtime dependencies into an isolated venv
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Use the same WORKDIR as the runtime stage so the resulting venv's script
# shebangs (#!/app/.venv/bin/python) remain valid after COPY --from=builder.
# Putting builder at a different path (e.g. /build) breaks every console_script
# in the venv with "exec: no such file or directory" at runtime.
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests first to leverage layer cache
COPY pyproject.toml uv.lock ./

# Install runtime deps only (no dev extras, no project itself).
# The project source is loaded via PYTHONPATH=/app/src in the runtime stage,
# not installed as a package — this also avoids needing README.md / src/ here
# and keeps the dep layer cache valid across pure source changes.
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: runtime — minimal image with venv + application source
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy the pre-built venv from builder (same path → shebangs valid)
COPY --from=builder /app/.venv /app/.venv

# Copy application source. pyproject.toml ships so get_version() can read
# [project].version at runtime — the package itself is not installed (see the
# builder's --no-install-project), so distribution metadata is absent.
COPY pyproject.toml ./pyproject.toml

# Windows BuildKit mis-detects COPY src/ as cached when mtime drifts.
# Placing ARG GIT_SHA here (after the venv and pyproject.toml layers) means a
# new commit sha invalidates only this layer and the src COPY below, while the
# expensive dep layers above remain cached.
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA

COPY src/ ./src/
COPY config/ ./config/
COPY alembic/ ./alembic/
COPY alembic/alembic.ini ./alembic.ini

# App runs from the isolated /app/.venv; system pip/setuptools/wheel are never
# on its import path. Remove them so their CVEs (and bulk) leave the image.
RUN python -m pip uninstall -y pip setuptools wheel

# Drop root: every service (api, worker, beat, migrate) runs as this user.
# /app stays owned by it because the worker/beat write runtime artifacts into
# the working directory (celery beat schedule, pipeline-events.jsonl); the
# config bind-mount is layered over /app/config read-only and never written.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && chown -R app:app /app
USER app

# Put venv binaries first on PATH so uv run resolves to the venv.
# PYTHONUTF8 / PYTHONIOENCODING are the process-level floor of the UTF-8
# encoding contract: they pin stdout/stderr, subprocess text streams and the
# filesystem-path codec to UTF-8 for every containerized process (api, worker,
# beat, migrate, cli), independent of the base image locale.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8

EXPOSE 8000

# Health probe uses the venv's Python (no curl in the image) — exit 0 only on HTTP 200.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys\ntry: sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=5).status==200 else 1)\nexcept Exception: sys.exit(1)"]

# Default entrypoint: API server.
# Override CMD to run worker or beat (compose uses the scheduler.boot app):
#   worker: celery -A intellisource.scheduler.boot worker --loglevel=info
#   beat:   celery -A intellisource.scheduler.boot beat --loglevel=info
CMD ["uvicorn", "intellisource.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
