# syntax=docker/dockerfile:1.6
# Build context is the repo root so /workspace picks up data/preprocessing.py
# and the model code. Build with:
#   docker build -f demo/agent_worker/Dockerfile -t agentguard-agent-worker .
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends stress-ng curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch wheel first so the layer is cached independently of project
# deps. data/preprocessing.py does `import torch` at module scope, so the
# worker must have torch installed even though encode_event itself doesn't
# actually touch torch.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.4.0"

# Copy pyproject first for dependency layer caching
COPY demo/agent_worker/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx numpy pytest pytest-asyncio

# Main repo so data.preprocessing etc. resolve via PYTHONPATH.
COPY . /workspace
ENV PYTHONPATH=/workspace

# Copy worker project (app/, fixtures/, tests/)
COPY demo/agent_worker/ /app/

# --- hardening for the live demo --------------------------------------------
# 1. Redirect injection-target hostnames to the in-cluster receiver. The
#    entrypoint will merge from /etc/hosts.append; on read-only mounts this
#    silently no-ops and Compose-level extra_hosts (Task 14) covers the case.
RUN printf 'attacker-receiver attacker.example.com c2.example.com evil.example.com\n' \
        >> /etc/hosts.append

# 2. Non-root user with /tmp scratch. chown after all COPYs so the worker user
#    actually owns the source it executes.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 10001 worker \
 && chown -R worker:worker /app

# 3. Entrypoint that merges /etc/hosts.append into /etc/hosts, then execs.
#    COPY happens as root (Docker COPY ignores USER). chmod is defensive: git
#    on Windows can lose the +x bit, so we don't rely on the source's mode.
COPY demo/agent_worker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

USER worker

EXPOSE 8200

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
