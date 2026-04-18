"""Per-feature z-score deviation vs. a per-agent benign baseline.

Exposes ``FEATURE_NAMES`` (length 32) matching the Stream 1 feature layout
produced by ``data.preprocessing.flatten_telemetry`` so reports can name the
features that deviate most.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from data.preprocessing import STAT_GROUPS


def _build_feature_names() -> List[str]:
    """Build the 32-entry FEATURE_NAMES list aligned with flatten_telemetry()."""
    names: List[str] = []
    for group in STAT_GROUPS:
        for stat in ("mean", "max", "min", "std"):
            names.append(f"{group}_{stat}")
    names.extend([
        "syscall_entropy",
        "unique_syscalls",
        "total_syscalls",
        "sample_count",
    ])
    return names


FEATURE_NAMES: List[str] = _build_feature_names()
assert len(FEATURE_NAMES) == 32, "FEATURE_NAMES must have exactly 32 entries"


def compute_benign_baseline(agent_id: str,
                            stream1_benign: np.ndarray) -> Dict[str, np.ndarray]:
    """Compute per-feature mean/std over benign windows for one agent.

    Args:
        agent_id: Only used for diagnostic error messages.
        stream1_benign: [N_benign, 32] raw Stream 1 features for this agent's
            benign windows.

    Returns:
        ``{"mean": np.ndarray[32], "std": np.ndarray[32]}``
    """
    arr = np.asarray(stream1_benign, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 32:
        raise ValueError(
            f"[{agent_id}] stream1_benign must be [N, 32], got shape {arr.shape}"
        )

    if arr.shape[0] == 0:
        # No benign windows observed — fall back to zero mean / unit std so
        # downstream code doesn't divide by zero and z-scores are not crazy.
        mean = np.zeros(32, dtype=np.float64)
        std = np.ones(32, dtype=np.float64)
    else:
        mean = arr.mean(axis=0)
        std = arr.std(axis=0)

    # Guard against zero / near-zero std for constant features.
    std = np.maximum(std, 1e-6)
    return {"mean": mean.astype(np.float64), "std": std.astype(np.float64)}


def feature_zscores(stream1_sample: np.ndarray,
                    baseline: Dict[str, np.ndarray]) -> Dict:
    """Compute per-feature z-scores for a single window.

    Args:
        stream1_sample: [32] raw Stream 1 vector for the window of interest.
        baseline: dict from :func:`compute_benign_baseline`.

    Returns:
        dict with keys:
            zscores: np.ndarray [32]
            top_k:   list of (feature_name, zscore, sample_value, baseline_mean)
                     sorted by absolute z-score desc (all 32 entries; caller
                     decides how many to display).
    """
    sample = np.asarray(stream1_sample, dtype=np.float64).reshape(-1)
    if sample.shape[0] != 32:
        raise ValueError(
            f"stream1_sample must be length 32, got shape {sample.shape}"
        )

    mean = np.asarray(baseline["mean"], dtype=np.float64)
    std = np.maximum(np.asarray(baseline["std"], dtype=np.float64), 1e-6)

    zscores = (sample - mean) / std

    order = np.argsort(-np.abs(zscores))
    ranked: List[Tuple[str, float, float, float]] = [
        (
            FEATURE_NAMES[int(i)],
            float(zscores[int(i)]),
            float(sample[int(i)]),
            float(mean[int(i)]),
        )
        for i in order
    ]

    return {
        "zscores": zscores,
        "top_k": ranked,
    }
