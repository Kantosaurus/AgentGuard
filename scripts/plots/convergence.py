"""
Convergence / training-curve figure.

Reads every `logs/seed*_fold*_epochs.csv` produced by
`utils.logging.EpochCSVWriter` and renders a 2x2 panel:

    A: train reconstruction loss   B: train contrastive loss
    C: train temporal loss         D: validation AUROC

Each panel overlays one thin alpha line per (seed, fold) run, coloured by
seed, plus a bold mean line with a shaded min-max envelope across all runs.
Handles different run lengths (early stopping) by right-padding shorter runs
with NaN and using nan-aware aggregation.

Output: `results/figures/convergence.pdf`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# When run as a script directly, make the package imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    FIGURES_DIR,
    SEED_COLORS,
    load_all_epoch_csvs,
    save_pdf,
)


# Panels: (col_in_csv, axis title, y-label)
PANELS = [
    ("train_recon", "Reconstruction loss (train)", "loss"),
    ("train_contrastive", "Contrastive loss (train)", "loss"),
    ("train_temporal", "Temporal loss (train)", "loss"),
    ("auroc", "Validation AUROC", "AUROC"),
]


def _pad_to_matrix(series_list, max_len):
    """Stack 1-D arrays into a [n_runs, max_len] matrix, NaN-padded on the right."""
    mat = np.full((len(series_list), max_len), np.nan, dtype=float)
    for i, s in enumerate(series_list):
        n = min(len(s), max_len)
        mat[i, :n] = np.asarray(s, dtype=float)[:n]
    return mat


def build_figure(runs, seed_colors=None):
    """`runs` is a list of dicts {seed, fold, df}. Returns a matplotlib Figure."""
    if seed_colors is None:
        seed_colors = SEED_COLORS

    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=False)
    axes = axes.flatten()

    # Longest run across every (seed, fold) in the directory.
    max_len = max((len(r["df"]) for r in runs), default=0)
    if max_len == 0:
        for ax in axes:
            ax.text(0.5, 0.5, "no epoch CSVs found",
                    ha="center", va="center", transform=ax.transAxes)
        return fig

    epochs_axis = np.arange(1, max_len + 1)

    for ax, (col, title, ylabel) in zip(axes, PANELS):
        series_list, seeds_for_rows = [], []
        for r in runs:
            df = r["df"]
            if col not in df.columns or df[col].dropna().empty:
                continue
            series_list.append(df[col].to_numpy())
            seeds_for_rows.append(r["seed"])

            ax.plot(
                np.arange(1, len(df) + 1),
                df[col].to_numpy(),
                color=seed_colors.get(r["seed"], "#888888"),
                alpha=0.3,
                lw=0.9,
                zorder=1,
            )

        if not series_list:
            ax.text(0.5, 0.5, f"no '{col}' values",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            continue

        mat = _pad_to_matrix(series_list, max_len)
        with np.errstate(all="ignore"):
            mean_curve = np.nanmean(mat, axis=0)
            lo_curve = np.nanmin(mat, axis=0)
            hi_curve = np.nanmax(mat, axis=0)

        # Only plot across epochs where at least one run has a value.
        valid = ~np.isnan(mean_curve)
        if valid.any():
            ax.fill_between(
                epochs_axis[valid], lo_curve[valid], hi_curve[valid],
                color="black", alpha=0.1, zorder=2, label="min-max across runs",
            )
            ax.plot(
                epochs_axis[valid], mean_curve[valid],
                color="black", lw=2.0, zorder=3, label="mean across runs",
            )

        ax.set_title(title)
        ax.set_xlabel("epoch")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25)

        # Legend collates seed colours plus the mean/envelope.
        seed_handles, seen = [], set()
        for r in runs:
            s = r["seed"]
            if s in seen:
                continue
            seen.add(s)
            seed_handles.append(
                plt.Line2D([], [], color=seed_colors.get(s, "#888888"),
                           alpha=0.7, lw=1.3, label=f"seed {s}")
            )
        extra = [
            plt.Line2D([], [], color="black", lw=2.0, label="mean"),
            plt.Line2D([], [], color="black", alpha=0.15, lw=6, label="min-max"),
        ]
        ax.legend(handles=seed_handles + extra, fontsize=7, loc="best", framealpha=0.85)

    fig.suptitle("Training convergence across seeds and folds", y=1.01, fontsize=13)
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--logs-dir", default="logs", help="Directory holding per-run *_epochs.csv files")
    parser.add_argument("--out-dir", default=str(FIGURES_DIR), help="Output directory for the PDF")
    parser.add_argument("--filename", default="convergence.pdf", help="PDF filename")
    args = parser.parse_args(argv)

    runs = load_all_epoch_csvs(base_dir=args.logs_dir)
    if not runs:
        print(f"[convergence] warning: no epoch CSVs found under {args.logs_dir!r}", file=sys.stderr)

    fig = build_figure(runs)
    out = save_pdf(fig, args.filename, figures_dir=Path(args.out_dir))
    plt.close(fig)
    print(f"[convergence] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
