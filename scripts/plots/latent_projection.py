"""
Latent-projection figures (t-SNE + UMAP).

Loads every `latents/agentguard_seed*_fold*.npz`, concatenates the latent
vectors across runs, then projects them into 2D twice — once with t-SNE and
once with UMAP — using identical downsampled input so the two views are
directly comparable.

For each projection we emit a side-by-side two-panel figure:
    left:  points coloured by binary label (benign vs anomalous)
    right: points coloured by attack_category (9 classes + benign)

Outputs:
    results/figures/latent_tsne.pdf
    results/figures/latent_umap.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    CATEGORY_PALETTE,
    FIGURES_DIR,
    load_latents,
    save_pdf,
)


def _gather_latents(records):
    """Flatten a list of latent NPZ dicts into single X / labels / categories arrays.

    Benign points are relabelled to category "benign" for palette lookups.
    """
    X_parts, y_parts, cat_parts = [], [], []
    for r in records:
        if "latent" not in r:
            continue
        latent = np.asarray(r["latent"])
        if latent.ndim != 2:
            continue
        N = latent.shape[0]

        y_true = np.asarray(r.get("y_true", np.zeros(N, dtype=int)))
        cats = r.get("attack_category", None)
        if cats is None:
            cats = np.full(N, "", dtype=object)
        else:
            cats = np.asarray(cats, dtype=object)

        # Unify benign samples under a single "benign" bucket.
        resolved = np.empty(N, dtype=object)
        for i in range(N):
            if int(y_true[i]) == 0 or not cats[i]:
                resolved[i] = "benign"
            else:
                resolved[i] = str(cats[i])

        X_parts.append(latent)
        y_parts.append(y_true.astype(int))
        cat_parts.append(resolved)

    if not X_parts:
        return None

    X = np.concatenate(X_parts, axis=0)
    y = np.concatenate(y_parts, axis=0)
    cat = np.concatenate(cat_parts, axis=0)
    return X, y, cat


def _stratified_subsample(X, y, cat, max_samples, rng):
    """Stratified downsample by binary label to keep class ratios stable."""
    if max_samples is None or X.shape[0] <= max_samples:
        return X, y, cat

    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    total = X.shape[0]
    frac_pos = len(idx_pos) / total

    n_pos = min(len(idx_pos), int(round(max_samples * frac_pos)))
    n_neg = min(len(idx_neg), max_samples - n_pos)

    pick_pos = rng.choice(idx_pos, n_pos, replace=False) if n_pos > 0 else np.array([], int)
    pick_neg = rng.choice(idx_neg, n_neg, replace=False) if n_neg > 0 else np.array([], int)
    picks = np.sort(np.concatenate([pick_pos, pick_neg]))
    return X[picks], y[picks], cat[picks]


def _project_tsne(X, random_state=42):
    from sklearn.manifold import TSNE
    # Perplexity must be strictly < n_samples; clamp for tiny test inputs.
    perp = min(30, max(2, X.shape[0] - 2))
    return TSNE(
        n_components=2, perplexity=perp, random_state=random_state, init="pca",
    ).fit_transform(X)


def _project_umap(X, random_state=42):
    import umap
    n_neighbors = min(15, max(2, X.shape[0] - 1))
    reducer = umap.UMAP(
        n_neighbors=n_neighbors, min_dist=0.1, random_state=random_state,
    )
    return reducer.fit_transform(X)


def _plot_projection(emb, y, cat, title):
    """Two-panel figure: binary labels on the left, attack category on the right."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    # ── left: binary label ─────────────────────────────────────────────────
    ax = axes[0]
    mask_neg = y == 0
    mask_pos = y == 1
    ax.scatter(
        emb[mask_neg, 0], emb[mask_neg, 1],
        s=6, alpha=0.5, c="#BBBBBB", label="normal", linewidths=0,
    )
    ax.scatter(
        emb[mask_pos, 0], emb[mask_pos, 1],
        s=6, alpha=0.6, c="#d62728", label="anomalous", linewidths=0,
    )
    ax.set_title(f"{title} — label")
    ax.set_xlabel("component 1")
    ax.set_ylabel("component 2")
    ax.legend(loc="best", markerscale=1.8, framealpha=0.85)

    # ── right: attack category ─────────────────────────────────────────────
    ax = axes[1]
    cats_present = [c for c in CATEGORY_PALETTE if np.any(cat == c)]
    for c in cats_present:
        mask = cat == c
        ax.scatter(
            emb[mask, 0], emb[mask, 1],
            s=6, alpha=0.5 if c != "benign" else 0.3,
            c=CATEGORY_PALETTE[c], label=c, linewidths=0,
        )
    ax.set_title(f"{title} — attack category")
    ax.set_xlabel("component 1")
    ax.set_ylabel("component 2")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5),
              fontsize=8, markerscale=1.8, framealpha=0.85)

    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="t-SNE / UMAP latent projections")
    parser.add_argument("--latents-dir", default="latents")
    parser.add_argument("--out-dir", default=str(FIGURES_DIR))
    parser.add_argument("--max-samples", type=int, default=10000,
                        help="Stratified downsample cap before projection")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--skip-tsne", action="store_true")
    parser.add_argument("--skip-umap", action="store_true")
    args = parser.parse_args(argv)

    records = load_latents("agentguard", base_dir=args.latents_dir)
    if not records:
        print(f"[latent_projection] warning: no latent NPZs found under "
              f"{args.latents_dir!r}; emitting empty placeholder figures.",
              file=sys.stderr)
        for name in ("latent_tsne.pdf", "latent_umap.pdf"):
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.text(0.5, 0.5, "no latent data available",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            save_pdf(fig, name, figures_dir=Path(args.out_dir))
            plt.close(fig)
        return 0

    gathered = _gather_latents(records)
    if gathered is None:
        print("[latent_projection] error: no usable latent arrays", file=sys.stderr)
        return 1
    X, y, cat = gathered

    rng = np.random.default_rng(args.random_state)
    Xs, ys, cats = _stratified_subsample(X, y, cat, args.max_samples, rng)
    print(f"[latent_projection] projecting {Xs.shape[0]} points "
          f"({Xs.shape[1]}-D) from {len(records)} runs")

    if not args.skip_tsne:
        try:
            emb = _project_tsne(Xs, random_state=args.random_state)
            fig = _plot_projection(emb, ys, cats, "t-SNE")
            out = save_pdf(fig, "latent_tsne.pdf", figures_dir=Path(args.out_dir))
            plt.close(fig)
            print(f"[latent_projection] wrote {out}")
        except Exception as e:
            print(f"[latent_projection] t-SNE failed: {e}", file=sys.stderr)

    if not args.skip_umap:
        try:
            emb = _project_umap(Xs, random_state=args.random_state)
            fig = _plot_projection(emb, ys, cats, "UMAP")
            out = save_pdf(fig, "latent_umap.pdf", figures_dir=Path(args.out_dir))
            plt.close(fig)
            print(f"[latent_projection] wrote {out}")
        except Exception as e:
            print(f"[latent_projection] UMAP failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
