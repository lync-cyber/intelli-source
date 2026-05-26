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

# curl is needed for the HEALTHCHECK; procps for signal handling diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the pre-built venv from builder (same path → shebangs valid)
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY src/ ./src/
COPY config/ ./config/
COPY alembic/ ./alembic/
COPY alembic/alembic.ini ./alembic.ini

# Put venv binaries first on PATH so uv run resolves to the venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Default entrypoint: API server.
# Override CMD to run worker or beat:
#   worker: uv run celery -A intellisource.scheduler.celery_app worker --loglevel=info
#   beat:   uv run celery -A intellisource.scheduler.celery_app beat --loglevel=info
CMD ["uvicorn", "intellisource.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
