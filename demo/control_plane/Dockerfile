FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only torch first (smaller wheel, no CUDA) to warm the pip cache layer
# independently of the project files so iteration stays fast.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.4.0"

# Copy the control_plane project (pyproject + app package) and install its deps.
COPY demo/control_plane/ /app/
RUN pip install --no-cache-dir ".[test]"

# Main repo checked in at /workspace so model code + checkpoint + config resolve via PYTHONPATH.
COPY . /workspace
ENV PYTHONPATH=/workspace
ENV AGENTGUARD_CONFIG=/workspace/config.yml
ENV AGENTGUARD_CHECKPOINT=/workspace/data/processed/checkpoints/best_model.pt

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
