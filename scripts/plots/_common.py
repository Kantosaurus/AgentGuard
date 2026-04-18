"""
Shared helpers for Phase E plotting scripts.

All figure-producing scripts under scripts/plots/ import from this module to
stay consistent on seeds/folds, baseline names/order, colour palettes, and
the glob patterns used to discover per-seed-per-fold artifacts from Phases C
and D.
"""

from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ─── constants ────────────────────────────────────────────────────────────────

AGENTGUARD_CONFIG_PATH = "config_best.yml"

SEEDS: List[int] = [42, 1337, 2024]
FOLDS: List[int] = [1, 2, 3, 4, 5]

BASELINE_ORDER: List[str] = [
    "agentguard",
    "transformer_ae",
    "lstm_ae",
    "cnn_ae",
    "deep_svdd",
    "isolation_forest",
]

BASELINE_DISPLAY: Dict[str, str] = {
    "agentguard": "AgentGuard",
    "transformer_ae": "Transformer AE",
    "lstm_ae": "LSTM AE",
    "cnn_ae": "CNN AE",
    "deep_svdd": "Deep SVDD",
    "isolation_forest": "Isolation Forest",
}

# Distinct qualitative colour per baseline (colour-blind-safe tab10-ish).
BASELINE_COLORS: Dict[str, str] = {
    "agentguard": "#d62728",        # red — the star of the show
    "transformer_ae": "#1f77b4",    # blue
    "lstm_ae": "#2ca02c",           # green
    "cnn_ae": "#9467bd",            # purple
    "deep_svdd": "#ff7f0e",         # orange
    "isolation_forest": "#7f7f7f",  # grey
}

# One colour per seed for per-run convergence lines.
SEED_COLORS: Dict[int, str] = {
    42: "#1f77b4",
    1337: "#2ca02c",
    2024: "#d62728",
}

# 9 attack categories + benign. Values are hex strings — sourced from
# matplotlib's tab10/Set1 palettes (muted but distinct).
CATEGORY_PALETTE: Dict[str, str] = {
    "Exfiltration": "#1f77b4",
    "Goal Hijacking": "#ff7f0e",
    "Indirect Injection": "#2ca02c",
    "Persistence": "#d62728",
    "Privesc": "#9467bd",
    "Prompt Injection": "#8c564b",
    "Resource Abuse": "#e377c2",
    "Social Engineering": "#bcbd22",
    "Tool Chaining": "#17becf",
    "benign": "#CCCCCC",
}

FIGURES_DIR: Path = Path("results/figures")
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


# ─── filename parsing ────────────────────────────────────────────────────────

_SEED_FOLD_RE = re.compile(r"seed(?P<seed>\d+)_fold(?P<fold>\d+)")


def parse_seed_fold(path: str | os.PathLike) -> Optional[Dict[str, int]]:
    """Extract seed and fold integers from a filename like
    'isolation_forest_seed42_fold1.npz' or 'seed1337_fold3_epochs.csv'.
    Returns None if the pattern isn't present.
    """
    m = _SEED_FOLD_RE.search(str(path))
    if m is None:
        return None
    return {"seed": int(m.group("seed")), "fold": int(m.group("fold"))}


# ─── loaders ─────────────────────────────────────────────────────────────────

def load_predictions(pattern: str, base_dir: str = "predictions") -> List[Dict]:
    """Glob `{base_dir}/{pattern}_seed*_fold*.npz` and return a list of dicts.

    Each dict has the NPZ array keys as entries plus parsed `seed`, `fold`,
    and `path` for bookkeeping. Uses `allow_pickle=True` so that object-dtype
    arrays (attack_id strings, etc.) round-trip correctly.
    """
    paths = sorted(glob.glob(os.path.join(base_dir, f"{pattern}_seed*_fold*.npz")))
    out: List[Dict] = []
    for p in paths:
        meta = parse_seed_fold(p)
        if meta is None:
            continue
        with np.load(p, allow_pickle=True) as npz:
            entry = {k: npz[k] for k in npz.files}
        entry["seed"] = meta["seed"]
        entry["fold"] = meta["fold"]
        entry["path"] = p
        out.append(entry)
    return out


def load_latents(pattern: str, base_dir: str = "latents") -> List[Dict]:
    """Glob `{base_dir}/{pattern}_seed*_fold*.npz` for latent archives."""
    paths = sorted(glob.glob(os.path.join(base_dir, f"{pattern}_seed*_fold*.npz")))
    out: List[Dict] = []
    for p in paths:
        meta = parse_seed_fold(p)
        if meta is None:
            continue
        with np.load(p, allow_pickle=True) as npz:
            entry = {k: npz[k] for k in npz.files}
        entry["seed"] = meta["seed"]
        entry["fold"] = meta["fold"]
        entry["path"] = p
        out.append(entry)
    return out


def load_epoch_csv(seed: int, fold: int, base_dir: str = "logs") -> pd.DataFrame:
    """Load a single per-run epoch CSV produced by EpochCSVWriter.

    The canonical name is `seed{seed}_fold{fold}_epochs.csv` but falls back to
    a glob that matches any legacy naming that still carries the same tokens.
    Returns an empty DataFrame (with the expected columns) if no file found.
    """
    canonical = Path(base_dir) / f"seed{seed}_fold{fold}_epochs.csv"
    if canonical.exists():
        return pd.read_csv(canonical)
    matches = sorted(glob.glob(os.path.join(base_dir, f"*seed{seed}*fold{fold}*_epochs.csv")))
    if matches:
        return pd.read_csv(matches[0])
    return pd.DataFrame(columns=[
        "epoch", "train_total", "train_recon", "train_contrastive", "train_temporal",
        "val_total", "val_recon", "val_contrastive", "val_temporal",
        "auroc", "auprc", "f1", "precision", "recall", "lr",
    ])


def load_all_epoch_csvs(base_dir: str = "logs") -> List[Dict]:
    """Discover every `*seed*fold*_epochs.csv` in `base_dir` and load each
    as `{seed, fold, df}`. Handy when we don't know which seeds/folds ran.
    """
    paths = sorted(glob.glob(os.path.join(base_dir, "*seed*fold*_epochs.csv")))
    out: List[Dict] = []
    for p in paths:
        meta = parse_seed_fold(p)
        if meta is None:
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if df.empty:
            continue
        out.append({"seed": meta["seed"], "fold": meta["fold"], "df": df, "path": p})
    return out


# ─── figure saving ───────────────────────────────────────────────────────────

def save_pdf(fig, filename: str, figures_dir: Optional[Path] = None) -> Path:
    """Tight layout + save as a high-DPI PDF under `figures_dir` (default
    FIGURES_DIR). Returns the resolved output Path.
    """
    out_dir = Path(figures_dir) if figures_dir is not None else FIGURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        fig.tight_layout()
    except Exception:
        pass
    out_path = out_dir / filename
    fig.savefig(out_path, bbox_inches="tight", dpi=200)
    return out_path
