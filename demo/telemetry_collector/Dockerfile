# syntax=docker/dockerfile:1.6
#
# Build context: repo root (so COPY . /workspace brings in data/, models/, config.yml).
#   docker build -f demo/telemetry_collector/Dockerfile -t agentguard-telemetry:latest .
FROM python:3.11-slim

WORKDIR /app

# Install CPU-only torch first — separate layer so iteration on app code doesn't
# re-download the wheel every rebuild. data/preprocessing.py imports torch at
# module scope, so we need it even though Stream-1 aggregation is pure numpy.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.4.0"

# Install project + test deps against the pyproject (before copying app code, so
# dependency changes don't invalidate the cache when only source changes).
COPY demo/telemetry_collector/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.29" "numpy>=1.26" \
    "pytest>=8.0" "pytest-asyncio>=0.23" "httpx>=0.27"

# Main repo goes at /workspace so data.preprocessing resolves via PYTHONPATH.
COPY . /workspace
ENV PYTHONPATH=/workspace:/app

# Service code last — cheapest layer to invalidate.
COPY demo/telemetry_collector/ /app/

EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
