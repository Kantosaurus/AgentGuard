"""
ROC + PR comparison figure with 5/95 percentile bands.

For each model in BASELINE_ORDER:
  - glob `predictions/{model}_seed*_fold*.npz`
  - per run, compute (fpr, tpr) and (recall, precision)
  - interpolate each run's curve onto a common 200-point grid
  - stack into a [n_runs, 200] matrix and take mean / 5th / 95th percentile

Plot two panels side-by-side: ROC (left) and PR (right). Legend entries
report mean AUROC / AUPRC across runs.

Output: results/figures/roc_pr_comparison.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import (
    auc,
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BASELINE_COLORS,
    BASELINE_DISPLAY,
    BASELINE_ORDER,
    FIGURES_DIR,
    load_predictions,
    save_pdf,
)


GRID_POINTS = 200


def _safe_roc(y_true, y_score, grid):
    fpr, tpr, _ = roc_curve(y_true, y_score)
    # np.interp needs fpr monotonically non-decreasing, which roc_curve guarantees.
    tpr_grid = np.interp(grid, fpr, tpr, left=0.0, right=1.0)
    auroc = roc_auc_score(y_true, y_score)
    return tpr_grid, auroc


def _safe_pr(y_true, y_score, grid):
    precision, recall, _ = precision_recall_curve(y_true, y_score)
    # precision_recall_curve returns decreasing recall → flip for np.interp.
    order = np.argsort(recall)
    recall = recall[order]
    precision = precision[order]
    prec_grid = np.interp(grid, recall, precision, left=precision[0], right=precision[-1])
    auprc = average_precision_score(y_true, y_score)
    return prec_grid, auprc


def _aggregate_model(runs, roc_grid, pr_grid):
    tpr_rows, auroc_rows = [], []
    prec_rows, auprc_rows = [], []
    for r in runs:
        y_true = np.asarray(r.get("y_true"))
        y_score = np.asarray(r.get("y_score"))
        if y_true is None or y_score is None or y_true.size == 0:
            continue
        # Need at least one of each class for ROC / PR to be defined.
        uniq = np.unique(y_true)
        if uniq.size < 2:
            continue
        try:
            tpr_row, auroc = _safe_roc(y_true, y_score, roc_grid)
            prec_row, auprc = _safe_pr(y_true, y_score, pr_grid)
        except Exception:
            continue
        tpr_rows.append(tpr_row)
        auroc_rows.append(auroc)
        prec_rows.append(prec_row)
        auprc_rows.append(auprc)

    if not tpr_rows:
        return None

    return {
        "tpr": np.stack(tpr_rows, axis=0),
        "auroc": np.array(auroc_rows),
        "prec": np.stack(prec_rows, axis=0),
        "auprc": np.array(auprc_rows),
        "n_runs": len(tpr_rows),
    }


def build_figure(model_stats: Dict[str, Dict], roc_grid, pr_grid):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    ax_roc, ax_pr = axes

    ax_roc.plot([0, 1], [0, 1], color="#999999", lw=1.0, ls="--", zorder=1)

    for model in BASELINE_ORDER:
        stats = model_stats.get(model)
        color = BASELINE_COLORS.get(model, "#333333")
        display = BASELINE_DISPLAY.get(model, model)
        if stats is None:
            # Keep a placeholder entry in the legend so the reader sees which
            # baselines were expected but missing.
            ax_roc.plot([], [], color=color, label=f"{display} (no data)")
            ax_pr.plot([], [], color=color, label=f"{display} (no data)")
            continue

        mean_tpr = np.mean(stats["tpr"], axis=0)
        lo_tpr = np.percentile(stats["tpr"], 5, axis=0)
        hi_tpr = np.percentile(stats["tpr"], 95, axis=0)
        mean_auroc = float(np.mean(stats["auroc"]))

        mean_prec = np.mean(stats["prec"], axis=0)
        lo_prec = np.percentile(stats["prec"], 5, axis=0)
        hi_prec = np.percentile(stats["prec"], 95, axis=0)
        mean_auprc = float(np.mean(stats["auprc"]))

        n = stats["n_runs"]
        ax_roc.fill_between(roc_grid, lo_tpr, hi_tpr, color=color, alpha=0.18, zorder=2)
        ax_roc.plot(roc_grid, mean_tpr, color=color, lw=1.8, zorder=3,
                    label=f"{display}  AUROC={mean_auroc:.3f}  (n={n})")

        ax_pr.fill_between(pr_grid, lo_prec, hi_prec, color=color, alpha=0.18, zorder=2)
        ax_pr.plot(pr_grid, mean_prec, color=color, lw=1.8, zorder=3,
                   label=f"{display}  AUPRC={mean_auprc:.3f}  (n={n})")

    ax_roc.set_xlim(0, 1)
    ax_roc.set_ylim(0, 1.01)
    ax_roc.set_xlabel("False positive rate")
    ax_roc.set_ylabel("True positive rate")
    ax_roc.set_title("ROC (mean +/- 5/95 percentile bands)")
    ax_roc.grid(alpha=0.25)
    ax_roc.legend(fontsize=8, loc="lower right", framealpha=0.85)

    ax_pr.set_xlim(0, 1)
    ax_pr.set_ylim(0, 1.01)
    ax_pr.set_xlabel("Recall")
    ax_pr.set_ylabel("Precision")
    ax_pr.set_title("Precision-Recall (mean +/- 5/95 percentile bands)")
    ax_pr.grid(alpha=0.25)
    ax_pr.legend(fontsize=8, loc="lower left", framealpha=0.85)

    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ROC + PR comparison across baselines")
    parser.add_argument("--predictions-dir", default="predictions")
    parser.add_argument("--out-dir", default=str(FIGURES_DIR))
    parser.add_argument("--filename", default="roc_pr_comparison.pdf")
    args = parser.parse_args(argv)

    roc_grid = np.linspace(0.0, 1.0, GRID_POINTS)
    pr_grid = np.linspace(0.0, 1.0, GRID_POINTS)

    model_stats: Dict[str, Dict] = {}
    summary_lines: List[str] = []
    for model in BASELINE_ORDER:
        runs = load_predictions(model, base_dir=args.predictions_dir)
        if not runs:
            summary_lines.append(f"  {model}: 0 runs")
            continue
        stats = _aggregate_model(runs, roc_grid, pr_grid)
        if stats is None:
            summary_lines.append(f"  {model}: 0 usable runs (of {len(runs)})")
            continue
        model_stats[model] = stats
        summary_lines.append(
            f"  {model}: n={stats['n_runs']}  "
            f"AUROC={stats['auroc'].mean():.4f}  "
            f"AUPRC={stats['auprc'].mean():.4f}"
        )

    print("[roc_pr] per-model aggregation:")
    for line in summary_lines:
        print(line)

    fig = build_figure(model_stats, roc_grid, pr_grid)
    out = save_pdf(fig, args.filename, figures_dir=Path(args.out_dir))
    plt.close(fig)
    print(f"[roc_pr] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
