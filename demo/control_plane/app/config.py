"""Environment-variable-driven runtime config for the control plane.

Every value defaults to something sensible for the docker-compose demo stack.
Use env vars to override when running locally or inside CI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Frozen config snapshot built from environment variables."""

    checkpoint_path: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_CHECKPOINT",
            "/workspace/data/processed/checkpoints/best_model.pt",
        )
    )
    config_yaml: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_CONFIG", "/workspace/config.yml"
        )
    )
    threshold: float = field(
        default_factory=lambda: _env_float("AGENTGUARD_THRESHOLD", 0.5)
    )
    baseline_npy: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_BASELINE", "/app/shared/baseline_windows.npy"
        )
    )
    norm_stats: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_NORM", "/app/shared/norm_stats.json"
        )
    )
    worker_image: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_WORKER_IMAGE", "agentguard-agent-worker:latest"
        )
    )
    network_name: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_NETWORK", "agentguard-demo-net"
        )
    )
    telemetry_url: str = field(
        default_factory=lambda: _env_str(
            "AGENTGUARD_TELEMETRY", "http://telemetry-collector:8100"
        )
    )
    worker_port: int = 8200
    tick_sec: float = field(
        default_factory=lambda: _env_float("AGENTGUARD_TICK_SEC", 5.0)
    )
    # Benign completion: the agent-worker is a long-running FastAPI server, so
    # it doesn't exit after a behavior completes. If no kill fires within this
    # many seconds, we flip the run to COMPLETED and tear the worker down.
    run_timeout_sec: float = field(
        default_factory=lambda: _env_float("AGENTGUARD_RUN_TIMEOUT_SEC", 60.0)
    )
