"""Capture an idle Stream-1 baseline tensor for the demo.

Boots an idle ``agentguard-agent-worker:latest`` container on the shared demo
network, points the running telemetry-collector service at its host PID, waits
~250 s for a full (8, 32) sliding window to form, fetches it, and writes
``demo/shared/baseline_windows.npy``.

Run AFTER phase 4 builds the agent-worker image::

    docker compose up -d telemetry-collector
    python demo/control_plane/scripts/capture_baseline.py

This is a one-shot utility — the output artifact is then committed to the repo
so the control plane can subtract the baseline at inference time without re-running
the capture on every deploy.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Resolve the output path:
#   - When run from the host (file lives at demo/control_plane/scripts/capture_baseline.py),
#     parents[3] is the repo root and we write demo/shared/baseline_windows.npy directly.
#   - When run inside the control-plane container the script sits at /app/scripts/,
#     which has only two parents; we fall back to the AGENTGUARD_BASELINE env var
#     (the control-plane volume-mounts demo/shared at /app/shared), and if even
#     that's missing we write to /tmp.
_script = Path(__file__).resolve()
try:
    _repo_root = _script.parents[3]
    _default_out = _repo_root / "demo" / "shared" / "baseline_windows.npy"
except IndexError:
    _default_out = Path(
        os.environ.get("AGENTGUARD_BASELINE", "/app/shared/baseline_windows.npy")
    )
OUT_PATH = Path(os.environ.get("AGENTGUARD_BASELINE_OUT", str(_default_out)))

# Network + image names must match demo/docker-compose.yml (Phase 6 wiring).
NETWORK_NAME = os.environ.get("AGENTGUARD_DEMO_NETWORK", "agentguard-demo-net")
WORKER_IMAGE = os.environ.get("AGENTGUARD_WORKER_IMAGE", "agentguard-agent-worker:latest")
TELEMETRY_URL = os.environ.get(
    "AGENTGUARD_TELEMETRY_URL", "http://telemetry-collector:8100"
)
# seq_context (8) × window_size (30 s) = 240 s minimum. 10 s slack for boot.
CAPTURE_SECONDS = int(os.environ.get("AGENTGUARD_BASELINE_SECONDS", "250"))


def _fatal(msg: str, code: int = 2) -> None:
    print(f"[capture_baseline] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> int:
    # Imports deferred so ``--help``-style runs / unit tests don't require docker.
    try:
        import docker  # type: ignore
        import httpx  # type: ignore
        import numpy as np
    except ImportError as e:
        _fatal(
            f"missing dependency: {e}. Install with "
            "`pip install docker httpx numpy` inside the control_plane image."
        )

    client = docker.from_env()

    # Fail fast with a helpful message if phase 4's worker image isn't built yet.
    try:
        client.images.get(WORKER_IMAGE)
    except docker.errors.ImageNotFound:
        _fatal(
            f"image '{WORKER_IMAGE}' not found. Phase 4 must build the worker "
            "image before this script runs:\n"
            "    docker compose build agent-worker-template\n"
            "or\n"
            "    docker build -f demo/agent_worker/Dockerfile "
            f"-t {WORKER_IMAGE} ."
        )

    # Verify the demo network exists. capture_baseline only makes sense when the
    # telemetry-collector service is already up on the shared network.
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        _fatal(
            f"docker network '{NETWORK_NAME}' not found. Bring the stack up first:\n"
            "    docker compose up -d telemetry-collector"
        )

    print(f"[capture_baseline] launching idle worker on {NETWORK_NAME}")
    worker = client.containers.run(
        WORKER_IMAGE,
        name="agent-worker-baseline",
        network=NETWORK_NAME,
        detach=True,
        remove=True,
        environment={"AGENTGUARD_MODE": "idle"},
    )

    try:
        worker.reload()
        pid = worker.attrs["State"]["Pid"]
        if not pid:
            _fatal(f"worker has no host PID (state={worker.attrs['State']})")
        print(f"[capture_baseline] worker pid={pid}; pointing telemetry at it")

        r = httpx.post(f"{TELEMETRY_URL}/target/{pid}", timeout=10.0)
        r.raise_for_status()

        print(f"[capture_baseline] sleeping {CAPTURE_SECONDS}s for window to fill")
        time.sleep(CAPTURE_SECONDS)

        resp = httpx.get(f"{TELEMETRY_URL}/window", timeout=10.0)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("shape") != [8, 32]:
            _fatal(f"unexpected window shape: {payload.get('shape')}")

        arr = np.array(payload["data"], dtype=np.float32)
        assert arr.shape == (8, 32), arr.shape

        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling .tmp then rename, so a crashed run never leaves a
        # partially-written file on disk. numpy.save appends ".npy" unless the
        # path already ends in ".npy", so we give it a full ".npy" path that
        # encodes "tmp" in the stem instead.
        tmp = OUT_PATH.with_name(OUT_PATH.stem + ".tmp.npy")
        np.save(tmp, arr)
        tmp.replace(OUT_PATH)
        print(f"[capture_baseline] wrote {OUT_PATH} shape={arr.shape}")

    finally:
        try:
            worker.kill()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
