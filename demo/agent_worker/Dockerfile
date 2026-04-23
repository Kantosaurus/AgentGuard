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

EXPOSE 8200

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
