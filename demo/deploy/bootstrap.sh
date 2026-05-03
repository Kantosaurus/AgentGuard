#!/usr/bin/env bash
# demo/deploy/bootstrap.sh — fresh-VPS one-shot deploy. Idempotent.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/<you>/AgentGuard.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/agentguard}"

if [ "$(id -u)" -ne 0 ]; then
    echo "bootstrap: re-run as root (sudo $0)" >&2
    exit 1
fi

# 1. Install Docker if missing.
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi

# 2. Clone or update the repo.
if [ ! -d "$INSTALL_DIR/.git" ]; then
    git clone "$REPO_URL" "$INSTALL_DIR"
else
    git -C "$INSTALL_DIR" fetch --all
    git -C "$INSTALL_DIR" reset --hard origin/master
fi

cd "$INSTALL_DIR/demo"

# 3. Ensure .env exists; if not, prompt operator.
if [ ! -f .env ]; then
    cp deploy/.env.example .env
    echo
    echo "bootstrap: created demo/.env from template."
    echo "Edit it now (DOMAIN, BASIC_AUTH_HASH, AGENT_OAUTH_TOKEN), then re-run."
    exit 0
fi

# 4. Build + bring up the stack.
docker compose -f docker-compose.yml -f compose.prod.yml build
docker compose -f docker-compose.yml -f compose.prod.yml --profile build-only \
    build agent-worker-template
docker compose -f docker-compose.yml -f compose.prod.yml up -d

# 5. Capture an idle baseline on this host (CPU profile differs from a laptop).
echo "bootstrap: capturing idle baseline (~4.5 min) ..."
sleep 5
docker compose -f docker-compose.yml -f compose.prod.yml exec -T control-plane \
    python /app/scripts/capture_baseline.py
docker compose -f docker-compose.yml -f compose.prod.yml restart control-plane

echo
echo "bootstrap: stack up at https://$(grep ^DOMAIN= .env | cut -d= -f2)"
echo "Logs: docker compose -f docker-compose.yml -f compose.prod.yml logs -f"
