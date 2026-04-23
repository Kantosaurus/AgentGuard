"""Export per-feature mean/std for the Stream-1 tensor from processed training data.

This mirrors the z-score normalization that ``data/dataset/telemetry_dataset.py``
computes at dataloader construction time (see lines ~72-76 there):

    all_stream1 = torch.cat([d["stream1"] for d in self.agent_data], dim=0)
    self.stream1_mean = all_stream1.mean(dim=0)
    self.stream1_std  = all_stream1.std(dim=0).clamp(min=1e-8)

We replicate that exact computation across every ``data/processed/agent-*.pt``
so the demo normalizes windows the same way training did.

Writes ``demo/shared/norm_stats.json`` as::

    {"mean": [32 floats], "std": [32 floats]}

Run from the repo root::

    python demo/control_plane/scripts/export_norm_stats.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch


REPO_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUT_PATH = REPO_ROOT / "demo" / "shared" / "norm_stats.json"


def compute_norm_stats(processed_dir: Path) -> tuple[list[float], list[float]]:
    """Concatenate every agent's stream1 tensor and compute column-wise mean/std."""
    pt_files = sorted(processed_dir.glob("agent-*.pt"))
    if not pt_files:
        raise FileNotFoundError(
            f"No agent-*.pt files found in {processed_dir}. "
            "Run the preprocessing pipeline first."
        )

    chunks: list[torch.Tensor] = []
    for p in pt_files:
        data = torch.load(p, map_location="cpu", weights_only=False)
        s1 = data["stream1"]
        if s1.ndim != 2 or s1.shape[1] != 32:
            raise ValueError(
                f"{p}: expected stream1 shape [*, 32], got {tuple(s1.shape)}"
            )
        chunks.append(s1.float())

    stacked = torch.cat(chunks, dim=0)
    mean = stacked.mean(dim=0)
    std = stacked.std(dim=0).clamp(min=1e-8)
    return mean.tolist(), std.tolist()


def main() -> int:
    print(f"[norm_stats] reading {PROCESSED_DIR}")
    mean, std = compute_norm_stats(PROCESSED_DIR)
    assert len(mean) == 32 and len(std) == 32
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        json.dump({"mean": mean, "std": std}, f, indent=2)
    print(f"[norm_stats] wrote {OUT_PATH}")
    print(f"[norm_stats] mean[:4]={[round(m, 4) for m in mean[:4]]}")
    print(f"[norm_stats] std[:4] ={[round(s, 4) for s in std[:4]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
