"""Loaders for the pre-seed baseline window and the per-feature norm stats.

Both artifacts are produced by Phase 2 and dropped into ``demo/shared/``. When
they are absent (running tests standalone, pre-Phase-2 snapshot) we fall back
to neutral values so the rest of the stack still exercises cleanly.
"""
from __future__ import annotations

import json
import os
from typing import Tuple

import numpy as np

from .config import Config


_STREAM1_DIM = 32
_SEQ_CONTEXT = 8


def load_baseline(cfg: Config) -> np.ndarray:
    """Return the pre-seed 8x32 baseline window.

    Falls back to a zero tensor with a loud warning when the artifact is
    missing so tests don't explode in the CI image (Phase 2 may not have run
    yet).
    """
    if not os.path.exists(cfg.baseline_npy):
        print(
            f"WARN: baseline missing at {cfg.baseline_npy}, using zeros",
            flush=True,
        )
        return np.zeros((_SEQ_CONTEXT, _STREAM1_DIM), dtype=np.float32)
    arr = np.load(cfg.baseline_npy).astype(np.float32)
    if arr.shape != (_SEQ_CONTEXT, _STREAM1_DIM):
        print(
            f"WARN: baseline shape {arr.shape} != ({_SEQ_CONTEXT}, {_STREAM1_DIM}); "
            "reshaping/padding to expected",
            flush=True,
        )
        fixed = np.zeros((_SEQ_CONTEXT, _STREAM1_DIM), dtype=np.float32)
        rows = min(_SEQ_CONTEXT, arr.shape[0])
        cols = min(_STREAM1_DIM, arr.shape[1]) if arr.ndim == 2 else 0
        if arr.ndim == 2:
            fixed[:rows, :cols] = arr[:rows, :cols]
        return fixed
    return arr


def load_norm(cfg: Config) -> Tuple[np.ndarray, np.ndarray]:
    """Return (mean, std) vectors of length 32 used to normalize Stream 1.

    If the stats file is missing we fall back to mean=zeros, std=ones so the
    transformation is the identity (still with the 1e-6 epsilon guard below).
    """
    if not os.path.exists(cfg.norm_stats):
        print(
            f"WARN: norm stats missing at {cfg.norm_stats}, using mean=0 / std=1",
            flush=True,
        )
        mean = np.zeros(_STREAM1_DIM, dtype=np.float32)
        std = np.ones(_STREAM1_DIM, dtype=np.float32)
        return mean, std + 1e-6
    with open(cfg.norm_stats) as f:
        d = json.load(f)
    mean = np.asarray(d["mean"], dtype=np.float32)
    std = np.asarray(d["std"], dtype=np.float32) + 1e-6
    return mean, std
