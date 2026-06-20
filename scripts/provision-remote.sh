#!/usr/bin/env bash
# provision-remote.sh — idempotent remote host setup for IntelliSource
#
# Usage:
#   sudo bash provision-remote.sh [--working-dir /opt/intellisource] [--dry-run]
#
# Covers:
#   - Docker / Docker Compose v2 presence check
#   - docker/.env initialisation from .env.example
#   - UFW firewall rules (22/80/443 allow; 8000/9090 deny)
#   - systemd unit installation (docker/intellisource.service template)
#   - Image pull from GHCR registry (docker-compose.registry.yml)
#   - Nginx/Caddy config sample generation with certbot reminder
#
# Re-running the script is safe; every step checks whether the target state
# already holds before applying a change.

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
WORKING_DIR="/opt/intellisource"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --working-dir)
            WORKING_DIR="$2"; shift 2 ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--working-dir <path>] [--dry-run]" >&2
            exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[provision] $*"; }
warn() { echo "[provision] WARN: $*" >&2; }
run()  {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[dry-run] $*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# §1  Prerequisite checks — Docker & Docker Compose v2
# ---------------------------------------------------------------------------
log "§1 Checking Docker prerequisites..."

if ! command -v docker &>/dev/null; then
    echo ""
    echo "ERROR: 'docker' not found in PATH." >&2
    echo "Install Docker Engine (https://docs.docker.com/engine/install/) and re-run." >&2
    exit 1
fi

DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
DOCKER_MAJOR=$(echo "$DOCKER_VERSION" | cut -d. -f1)
if [[ "$DOCKER_MAJOR" -lt 24 ]]; then
    warn "Docker Engine ${DOCKER_VERSION} detected; deploy-spec requires ≥ 24.x."
    warn "Upgrade with: https://docs.docker.com/engine/install/"
fi

# Docker Compose v2 ships as `docker compose` (plugin), not standalone `docker-compose`.
if ! docker compose version &>/dev/null; then
    echo ""
    echo "ERROR: Docker Compose v2 plugin not found." >&2
    echo "Install with: apt install docker-compose-plugin  (Debian/Ubuntu)" >&2
    echo "or follow: https://docs.docker.com/compose/install/" >&2
    exit 1
fi

log "Docker OK: $(docker --version)"
log "Compose OK: $(docker compose version)"

# ---------------------------------------------------------------------------
# §2  Resolve working directory
# ---------------------------------------------------------------------------
log "§2 Working directory: ${WORKING_DIR}"

if [[ ! -d "${WORKING_DIR}" ]]; then
    echo ""
    echo "ERROR: Working directory '${WORKING_DIR}' does not exist." >&2
    echo "Clone the repository there first:" >&2
    echo "  git clone https://github.com/lync-cyber/intelli-source ${WORKING_DIR}" >&2
    exit 1
fi

if [[ ! -f "${WORKING_DIR}/docker/docker-compose.yml" ]]; then
    echo "ERROR: docker/docker-compose.yml not found in '${WORKING_DIR}'. Is this the correct repo root?" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# §3  docker/.env initialisation
# ---------------------------------------------------------------------------
log "§3 Checking docker/.env..."

ENV_FILE="${WORKING_DIR}/docker/.env"
ENV_EXAMPLE="${WORKING_DIR}/docker/.env.example"

if [[ -f "${ENV_FILE}" ]]; then
    log "docker/.env already exists — skipping copy."
else
    if [[ ! -f "${ENV_EXAMPLE}" ]]; then
        warn "docker/.env.example not found; cannot initialise docker/.env."
    else
        run cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        run chmod 600 "${ENV_FILE}"
        echo ""
        echo "=================================================================="
        echo "  ACTION REQUIRED: fill in HIGH-sensitivity secrets in:"
        echo "    ${ENV_FILE}"
        echo ""
        echo "  Mandatory variables (change from placeholder values):"
        echo "    IS_DB_PASSWORD          — PostgreSQL password"
        echo "    IS_DATABASE_URL         — must embed the same password"
        echo "    IS_REDIS_PASSWORD       — Redis password"
        echo "    IS_REDIS_URL / IS_CELERY_BROKER_URL / IS_CELERY_RESULT_BACKEND"
        echo "                            — must embed the Redis password"
        echo "    IS_API_KEY              — API bearer token (strong random string)"
        echo "    OPENAI_API_KEY /        — LLM provider credentials"
        echo "    ANTHROPIC_API_KEY"
        echo "=================================================================="
        echo ""
    fi
fi

# ---------------------------------------------------------------------------
# §4  UFW firewall rules
# ---------------------------------------------------------------------------
log "§4 Configuring UFW firewall..."

if ! command -v ufw &>/dev/null; then
    warn "'ufw' not installed — skipping firewall configuration."
    warn "Ensure your host firewall / cloud security group allows 22/80/443"
    warn "and blocks 8000/9090/5432/6379 from public access."
else
    # Ensure outgoing is allowed before tightening incoming
    run ufw --force default deny incoming
    run ufw --force default allow outgoing
    run ufw allow 22/tcp
    run ufw allow 80/tcp
    run ufw allow 443/tcp
    # INPUT-chain deny (belt-and-suspenders; Docker FORWARD rules may bypass UFW).
    # See remote-host-readiness.md §4.2 for the Docker DOCKER-USER chain caveat.
    run ufw deny 8000/tcp
    run ufw deny 9090/tcp

    if [[ "$DRY_RUN" -eq 0 ]]; then
        # `ufw enable` is idempotent when already enabled
        echo "y" | ufw enable || true
        ufw status verbose
    else
        echo "[dry-run] ufw enable && ufw status verbose"
    fi
    log "UFW configured: allow 22/80/443; deny 8000/9090."
fi

# ---------------------------------------------------------------------------
# §5  Nginx config sample generation
# ---------------------------------------------------------------------------
log "§5 Generating nginx config sample..."

NGINX_CONF_TARGET="/etc/nginx/sites-available/intellisource"
NGINX_CONF_SAMPLE="${WORKING_DIR}/docker/nginx-intellisource.conf.sample"

# Always (re-)write the sample to the repo; actual /etc/nginx install is manual.
if [[ "$DRY_RUN" -eq 0 ]]; then
    cat > "${NGINX_CONF_SAMPLE}" <<'NGINX'
# IntelliSource nginx reverse-proxy configuration sample.
# Copy to /etc/nginx/sites-available/intellisource and adjust your domain.
# Enable with:
#   sudo ln -s /etc/nginx/sites-available/intellisource /etc/nginx/sites-enabled/
#   sudo nginx -t && sudo systemctl reload nginx
#
# Then obtain TLS:
#   sudo certbot --nginx -d your-domain.example.com

server {
    listen 80;
    server_name your-domain.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.example.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /health {
        proxy_pass       http://127.0.0.1:8000/health;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/v1/webhooks/ {
        proxy_pass       http://127.0.0.1:8000/api/v1/webhooks/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }

    location /api/ {
        proxy_pass       http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering  off;
        proxy_cache      off;
    }

    location /chat {
        proxy_pass       http://127.0.0.1:8000/chat;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX
    log "Nginx sample written to: ${NGINX_CONF_SAMPLE}"
else
    echo "[dry-run] Would write nginx sample to: ${NGINX_CONF_SAMPLE}"
fi

if [[ -f "${NGINX_CONF_TARGET}" ]]; then
    log "Nginx config already present at ${NGINX_CONF_TARGET} — skipping install."
else
    echo ""
    echo "=================================================================="
    echo "  ACTION REQUIRED (nginx/TLS):"
    echo "    1. Review and customise: ${NGINX_CONF_SAMPLE}"
    echo "    2. sudo cp ${NGINX_CONF_SAMPLE} ${NGINX_CONF_TARGET}"
    echo "    3. sudo ln -s ${NGINX_CONF_TARGET} /etc/nginx/sites-enabled/"
    echo "    4. sudo nginx -t && sudo systemctl reload nginx"
    echo "    5. sudo certbot --nginx -d your-domain.example.com"
    echo "=================================================================="
    echo ""
fi

# ---------------------------------------------------------------------------
# §6  systemd unit installation
# ---------------------------------------------------------------------------
log "§6 Installing systemd unit..."

SERVICE_TEMPLATE="${WORKING_DIR}/docker/intellisource.service"
SERVICE_TARGET="/etc/systemd/system/intellisource.service"

if [[ ! -f "${SERVICE_TEMPLATE}" ]]; then
    warn "Service template not found: ${SERVICE_TEMPLATE}"
    warn "Cannot install systemd unit."
else
    # Render the template: substitute __WORKING_DIRECTORY__ placeholder.
    if [[ "$DRY_RUN" -eq 0 ]]; then
        sed "s|__WORKING_DIRECTORY__|${WORKING_DIR}|g" \
            "${SERVICE_TEMPLATE}" > "${SERVICE_TARGET}"
        chmod 644 "${SERVICE_TARGET}"
        systemctl daemon-reload
        systemctl enable intellisource.service
        log "systemd unit installed and enabled: ${SERVICE_TARGET}"
        log "Start with: systemctl start intellisource.service"
    else
        echo "[dry-run] Would install systemd unit to: ${SERVICE_TARGET}"
        echo "[dry-run] WorkingDirectory would be set to: ${WORKING_DIR}"
        echo "[dry-run] systemctl daemon-reload && systemctl enable intellisource.service"
    fi
fi

# ---------------------------------------------------------------------------
# §7  Pull images from GHCR
# ---------------------------------------------------------------------------
log "§7 Pulling images from GHCR..."

COMPOSE_BASE="-f ${WORKING_DIR}/docker/docker-compose.yml"
COMPOSE_REGISTRY="-f ${WORKING_DIR}/docker/docker-compose.registry.yml"

# Login check: `docker login ghcr.io` must have been performed by the operator
# before running this script (or a token must be present in ~/.docker/config.json).
if run docker compose ${COMPOSE_BASE} ${COMPOSE_REGISTRY} pull; then
    log "Images pulled successfully."
else
    warn "Image pull failed. Ensure you are logged in to GHCR:"
    warn "  echo \$CR_PAT | docker login ghcr.io -u <github-username> --password-stdin"
    warn "Alternatively, set IS_IMAGE_TAG / IS_DB_IMAGE_TAG env vars to target a specific tag."
    exit 1
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "  Provisioning complete."
echo ""
echo "  Next steps:"
echo "    1. Fill in secrets in ${ENV_FILE}"
echo "    2. Configure nginx + TLS (see ${NGINX_CONF_SAMPLE})"
echo "    3. systemctl start intellisource.service"
echo "    4. systemctl status intellisource.service"
echo "    5. Verify: curl -fsS http://localhost:8000/health"
echo "=================================================================="
