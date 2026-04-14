"""
Cross-attention heatmap figure (optionally augmented with IG attribution).

Loads `config_best.yml` and a single checkpoint (seed=42, fold=1 by default),
rebuilds the fold-1 test loader via `main.build_loaders_from_splits`, runs the
model with `return_attention=True` on the anomalous test samples only, and
aggregates `attention_weights["1to2"]` per attack_category by averaging over
heads and samples within that category.

The resulting [T1, T2] heatmaps are laid out on a grid, one per category. If
`agentguard.interpretability.temporal_attribution` is importable (Phase F),
an integrated-gradients attribution heatmap is added as an extra row.

Output: results/figures/attention_by_category.pdf
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import CATEGORY_PALETTE, FIGURES_DIR, save_pdf  # noqa: E402

# Add the repo root to sys.path so `main`, `models`, `data` resolve.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _grid_shape(n):
    """Pick a (rows, cols) grid close to square for `n` cells."""
    cols = int(math.ceil(math.sqrt(max(1, n))))
    rows = int(math.ceil(n / cols))
    return rows, cols


def _plot_grid(category_maps, ig_map=None, title="Cross-attention (1->2) by attack category"):
    """Lay out one heatmap per category; optionally append an IG panel."""
    n_cells = len(category_maps) + (1 if ig_map is not None else 0)
    rows, cols = _grid_shape(n_cells)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 3.0), squeeze=False)

    items = list(category_maps.items())
    if ig_map is not None:
        items = items + [("IG attribution (all attacks)", ig_map)]

    for i in range(rows * cols):
        ax = axes[i // cols][i % cols]
        if i >= len(items):
            ax.set_axis_off()
            continue
        label, mat = items[i]
        if mat is None or np.size(mat) == 0:
            ax.set_axis_off()
            ax.set_title(f"{label}\n(no samples)", fontsize=9)
            continue
        im = ax.imshow(mat, aspect="auto", cmap="viridis", origin="upper")
        ax.set_title(label, fontsize=9)
        ax.set_xlabel("Action position (T2)", fontsize=8)
        ax.set_ylabel("Telemetry window step (T1)", fontsize=8)
        ax.tick_params(labelsize=7)
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

    fig.suptitle(title, fontsize=12, y=1.01)
    return fig


def _load_yaml(path):
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def _fake_fallback_figure(out_dir: Path, filename: str, msg: str):
    """Emit a placeholder PDF so downstream pipelines always have a file."""
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes,
            fontsize=10, wrap=True)
    ax.set_axis_off()
    path = save_pdf(fig, filename, figures_dir=out_dir)
    plt.close(fig)
    return path


def _collect_attention(model, loader, device):
    """Walk a DataLoader of anomalous samples and collect attention tensors,
    bucketed by attack_category (string). Returns a dict:
        {category: list of [H, T1, T2] arrays, one per sample}
    plus a running list for 'all_attacks'.
    """
    import torch

    by_cat: dict[str, list] = {}
    all_attacks: list = []

    model.eval()
    with torch.no_grad():
        for batch in loader:
            if batch is None:
                continue
            labels = batch["label"]
            keep = (labels == 1).nonzero(as_tuple=True)[0]
            if keep.numel() == 0:
                continue

            s1 = batch["stream1"][keep].to(device)
            s2_seq = batch["stream2_seq"][keep].to(device)
            s2_mask = batch["stream2_mask"][keep].to(device)

            out = model(s1, s2_seq, s2_mask, return_attention=True)
            attn = out.get("attention_weights")
            if attn is None or "1to2" not in attn:
                return None, None
            w = attn["1to2"].cpu().numpy()  # [B, H, T1, T2]

            cats_full = batch["attack_category"]
            cats = [cats_full[i.item()] for i in keep]

            for i, c in enumerate(cats):
                c_str = str(c) if c not in (None, "") else "unknown"
                by_cat.setdefault(c_str, []).append(w[i])  # [H, T1, T2]
                all_attacks.append(w[i])

    return by_cat, all_attacks


def _reduce_to_heatmap(samples):
    """Average over sample and head axes → [T1, T2]."""
    if not samples:
        return None
    stacked = np.stack(samples, axis=0)  # [N, H, T1, T2]
    return stacked.mean(axis=(0, 1))


def _try_ig_attribution(model, loader, device, max_samples: int = 16):
    """Compute an averaged Integrated Gradients attribution over anomalous
    test samples using Phase F's `attribute_temporal`, if present.

    The returned heatmap is shaped [T1_or_seq_context, T2_features_or_positions]
    — we take absolute values, average features within each stream dimension
    to collapse to per-timestep magnitudes, and align Stream 1 (telemetry) on
    the y-axis and Stream 2 (action) on the x-axis for parity with the
    attention heatmaps. If the function is unavailable, returns None.
    """
    try:
        from agentguard.interpretability.temporal_attribution import (  # type: ignore
            attribute_temporal,
        )
    except Exception as exc:
        print(f"[attention_heatmap] IG module unavailable ({exc}); "
              f"skipping IG panel", file=sys.stderr)
        return None

    import torch

    accum = None  # [T1, T2]
    count = 0
    try:
        for batch in loader:
            if batch is None or count >= max_samples:
                break
            labels = batch["label"]
            keep = (labels == 1).nonzero(as_tuple=True)[0]
            if keep.numel() == 0:
                continue
            for idx in keep.tolist():
                if count >= max_samples:
                    break
                s1 = batch["stream1"][idx:idx + 1].to(device)
                s2_seq = batch["stream2_seq"][idx:idx + 1].to(device)
                s2_mask = batch["stream2_mask"][idx:idx + 1].to(device)
                attr = attribute_temporal(model, s1, s2_seq, s2_mask)
                # [T1, F1] and [T2, F2] → magnitude per timestep
                s1_ts = attr["stream1_attr"].abs().mean(dim=-1).cpu().numpy()  # [T1]
                s2_ts = attr["stream2_attr"].abs().mean(dim=-1).cpu().numpy()  # [T2]
                # Outer product gives a comparable 2-D heatmap [T1, T2].
                heat = np.outer(s1_ts, s2_ts)
                accum = heat if accum is None else (accum + heat)
                count += 1
    except Exception as exc:
        print(f"[attention_heatmap] IG attribution failed: {exc}", file=sys.stderr)
        return None

    if accum is None or count == 0:
        return None
    return accum / count


def run(config_path: str, checkpoint_path: str, seed: int, fold: int,
        out_dir: Path, filename: str) -> int:
    import torch

    try:
        from main import (  # type: ignore
            build_model, build_loaders_from_splits, make_stratified_folds,
        )
    except Exception as exc:
        msg = (f"[attention_heatmap] cannot import main.py "
               f"({exc}); emitting placeholder.")
        print(msg, file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, "attention heatmap unavailable")
        return 0

    config = _load_yaml(config_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    ckpt_path = Path(checkpoint_path)
    if not ckpt_path.exists():
        msg = (f"checkpoint not found: {ckpt_path}\n"
               f"attention heatmap skipped (expected from Phase C/D)")
        print(f"[attention_heatmap] {msg}", file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, msg)
        return 0

    try:
        model = build_model(config)
        ckpt = torch.load(str(ckpt_path), map_location=device, weights_only=False)
        state = ckpt.get("model_state_dict", ckpt) if isinstance(ckpt, dict) else ckpt
        model.load_state_dict(state)
        model.to(device)
    except Exception as exc:
        msg = f"failed to load model / checkpoint: {exc}"
        print(f"[attention_heatmap] {msg}", file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, msg)
        return 0

    data_cfg = config["data"]
    try:
        folds = make_stratified_folds(
            data_cfg["attacked_agents"], data_cfg["control_agents"],
            data_cfg["k_folds"],
        )
    except Exception as exc:
        msg = f"fold construction failed: {exc}"
        print(f"[attention_heatmap] {msg}", file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, msg)
        return 0

    fold_idx = fold - 1  # CSV filenames are 1-indexed, list is 0-indexed.
    k = data_cfg["k_folds"]
    test_agents = folds[fold_idx]
    val_agents = folds[(fold_idx + 1) % k]
    train_agents = [a for j, fs in enumerate(folds)
                    if j not in (fold_idx, (fold_idx + 1) % k)
                    for a in fs]

    try:
        _, _, test_loader = build_loaders_from_splits(
            config, train_agents, val_agents, test_agents,
        )
    except Exception as exc:
        msg = f"data loader construction failed: {exc}"
        print(f"[attention_heatmap] {msg}", file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, msg)
        return 0

    by_cat, all_attacks = _collect_attention(model, test_loader, device)
    if by_cat is None:
        msg = "model did not return attention_weights (fusion_strategy != cross_attention?)"
        print(f"[attention_heatmap] {msg}", file=sys.stderr)
        _fake_fallback_figure(out_dir, filename, msg)
        return 0

    category_maps = {}
    # Display categories in the palette's order when they're present in the data.
    ordered = [c for c in CATEGORY_PALETTE if c != "benign" and c in by_cat]
    for c in ordered:
        category_maps[c] = _reduce_to_heatmap(by_cat[c])
    # Any categories not in our palette (e.g. "unknown") append at the end.
    for c in by_cat:
        if c not in category_maps:
            category_maps[c] = _reduce_to_heatmap(by_cat[c])
    # Fallback aggregate panel.
    category_maps["all_attacks"] = _reduce_to_heatmap(all_attacks)

    ig_map = _try_ig_attribution(model, test_loader, device)

    fig = _plot_grid(category_maps, ig_map=ig_map)
    out = save_pdf(fig, filename, figures_dir=out_dir)
    plt.close(fig)
    print(f"[attention_heatmap] wrote {out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cross-attention heatmaps by attack category")
    parser.add_argument("--config", default="config_best.yml")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fold", type=int, default=1)
    parser.add_argument("--checkpoint", default=None,
                        help="Override checkpoint path (defaults to "
                             "data/processed/checkpoints/model_seed{seed}_fold{fold}.pt)")
    parser.add_argument("--out-dir", default=str(FIGURES_DIR))
    parser.add_argument("--filename", default="attention_by_category.pdf")
    args = parser.parse_args(argv)

    ckpt = args.checkpoint or (
        f"data/processed/checkpoints/model_seed{args.seed}_fold{args.fold}.pt"
    )
    return run(
        config_path=args.config,
        checkpoint_path=ckpt,
        seed=args.seed,
        fold=args.fold,
        out_dir=Path(args.out_dir),
        filename=args.filename,
    )


if __name__ == "__main__":
    raise SystemExit(main())
