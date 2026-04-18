"""Multi-seed AgentGuard training driver (Phase C).

Runs N seeds x K folds of AgentGuard training with stratified agent-level
folds. For each (seed, fold) run, writes:

    logs/seed{seed}_fold{fold}_epochs.csv
    data/processed/checkpoints/model_seed{seed}_fold{fold}.pt
    predictions/agentguard_seed{seed}_fold{fold}.npz
    latents/agentguard_seed{seed}_fold{fold}.npz

The predictions/latents .npz files are consumed downstream by the
plotting and interpretability phases.

Usage:
    python scripts/train_multiseed.py --config config_best.yml \\
        --seeds 42,1337,2024 --out_dir .

    python scripts/train_multiseed.py --config config_best.yml \\
        --seeds 42 --fast           # smoke test: 1 seed x 5 folds x 5 epochs
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import numpy as np
import torch
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from main import (
    build_loaders_from_splits,
    build_model,
    make_stratified_folds,
    set_global_seed,
)
from training.trainer import AgentGuardTrainer
from utils.logging import EpochCSVWriter


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def parse_seeds(raw):
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


@torch.no_grad()
def run_inference(model, loader, device):
    """Run inference on loader; collect per-sample tensors and metadata.

    Returns a dict of numpy arrays / lists aligned along the sample axis.
    """
    model.eval()

    y_true_parts = []
    y_score_parts = []
    latent_parts = []
    attack_id_list = []
    attack_category_list = []
    agent_id_list = []
    window_idx_parts = []

    for batch in loader:
        batch_on_device = {
            k: (v.to(device) if torch.is_tensor(v) else v)
            for k, v in batch.items()
        }
        outputs = model(
            batch_on_device["stream1"],
            batch_on_device["stream2_seq"],
            batch_on_device["stream2_mask"],
        )
        y_score_parts.append(outputs["anomaly_score"].squeeze(-1).detach().cpu())
        latent_parts.append(outputs["latent"].detach().cpu())
        y_true_parts.append(batch_on_device["label"].detach().cpu())
        window_idx_parts.append(batch_on_device["window_idx"].detach().cpu())
        attack_id_list.extend(batch["attack_id"])
        attack_category_list.extend(batch["attack_category"])
        agent_id_list.extend(batch["agent_id"])

    y_true = torch.cat(y_true_parts).numpy().astype(np.int64)
    y_score = torch.cat(y_score_parts).numpy().astype(np.float32)
    latent = torch.cat(latent_parts).numpy().astype(np.float32)
    window_idx = torch.cat(window_idx_parts).numpy().astype(np.int64)

    return {
        "y_true": y_true,
        "y_score": y_score,
        "latent": latent,
        "attack_id": np.asarray(attack_id_list, dtype=object),
        "attack_category": np.asarray(attack_category_list, dtype=object),
        "agent_id": np.asarray(agent_id_list, dtype=object),
        "window_idx": window_idx,
    }


def compute_auroc(y_true, y_score):
    """Test-set AUROC, handling single-class edge case."""
    from sklearn.metrics import roc_auc_score
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, y_score))


def run_one(base_config, seed, fold_idx, folds, out_dir, fast):
    """Train + evaluate one (seed, fold) run. Returns test AUROC."""
    k = len(folds)
    fold_num = fold_idx + 1

    # Reproducibility: set seed before building any data loaders / models.
    set_global_seed(seed)

    # Test = folds[i]; val = folds[(i+1) % k]; train = rest.
    test_agents = folds[fold_idx]
    val_agents = folds[(fold_idx + 1) % k]
    train_agents = []
    for j in range(k):
        if j != fold_idx and j != (fold_idx + 1) % k:
            train_agents.extend(folds[j])

    print(f"\n{'=' * 60}")
    print(f"[seed={seed} fold={fold_num}/{k}]")
    print(f"  Train: {train_agents}")
    print(f"  Val:   {val_agents}")
    print(f"  Test:  {test_agents}")
    print(f"{'=' * 60}")

    # Deep-copy the config for this run so --fast mutations don't leak across runs.
    config = copy.deepcopy(base_config)
    if fast:
        config["training"]["epochs"] = 5
        config["training"]["early_stopping_patience"] = 5

    train_loader, val_loader, test_loader = build_loaders_from_splits(
        config, train_agents, val_agents, test_agents,
    )

    model = build_model(config)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Output paths (all relative to out_dir).
    out_root = Path(out_dir)
    checkpoint_dir = out_root / "data" / "processed" / "checkpoints"
    logs_dir = out_root / "logs"
    predictions_dir = out_root / "predictions"
    latents_dir = out_root / "latents"
    for d in (checkpoint_dir, logs_dir, predictions_dir, latents_dir):
        d.mkdir(parents=True, exist_ok=True)

    checkpoint_path = checkpoint_dir / f"model_seed{seed}_fold{fold_num}.pt"
    # EpochCSVWriter internally turns "<path>.log" into "<path>_epochs.csv",
    # so pass a .log stem to get the desired CSV filename.
    epoch_csv_stub = logs_dir / f"seed{seed}_fold{fold_num}.log"

    epoch_csv = EpochCSVWriter(epoch_csv_stub)
    try:
        trainer = AgentGuardTrainer(
            model, train_loader, val_loader, config,
            device=device, checkpoint_path=checkpoint_path,
            epoch_csv=epoch_csv,
        )
        trainer.fit()
    finally:
        epoch_csv.close()

    # Reload best checkpoint onto the in-memory model.
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=True)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device)

    # Test-set inference with gradients disabled.
    infer = run_inference(model, test_loader, device)

    auroc = compute_auroc(infer["y_true"], infer["y_score"])

    # Save predictions (no latents) for the plotting phase.
    preds_path = predictions_dir / f"agentguard_seed{seed}_fold{fold_num}.npz"
    np.savez(
        preds_path,
        y_true=infer["y_true"],
        y_score=infer["y_score"],
        attack_id=infer["attack_id"],
        attack_category=infer["attack_category"],
        agent_id=infer["agent_id"],
        window_idx=infer["window_idx"],
    )

    # Save latents (with labels + metadata) for the interpretability phase.
    latents_path = latents_dir / f"agentguard_seed{seed}_fold{fold_num}.npz"
    np.savez(
        latents_path,
        latent=infer["latent"],
        y_true=infer["y_true"],
        attack_id=infer["attack_id"],
        attack_category=infer["attack_category"],
        agent_id=infer["agent_id"],
        window_idx=infer["window_idx"],
    )

    print(f"[seed={seed} fold={fold_num}] test AUROC={auroc:.4f}")
    print(f"  checkpoint: {checkpoint_path}")
    print(f"  epoch csv:  {str(epoch_csv_stub).replace('.log', '_epochs.csv')}")
    print(f"  preds:      {preds_path}")
    print(f"  latents:    {latents_path}")

    return auroc


def main():
    parser = argparse.ArgumentParser(
        description="AgentGuard multi-seed x k-fold training driver (Phase C)."
    )
    parser.add_argument("--config", default="config_best.yml", help="Path to config YAML.")
    parser.add_argument("--seeds", default="42,1337,2024",
                        help="Comma-separated list of seeds (default: 42,1337,2024).")
    parser.add_argument("--out_dir", default=".",
                        help="Root directory for output artifacts (default: cwd).")
    parser.add_argument("--fast", action="store_true",
                        help="Smoke-test mode: override epochs to 5 and patience to 5.")
    parser.add_argument("--epochs", type=int, default=None,
                        help="Override config epochs (and early_stopping_patience = epochs).")
    parser.add_argument("--folds", default=None,
                        help="Comma-separated 1-indexed fold list (default: all folds).")
    args = parser.parse_args()

    seeds = parse_seeds(args.seeds)
    base_config = load_config(args.config)

    if args.epochs is not None:
        base_config["training"]["epochs"] = int(args.epochs)
        base_config["training"]["early_stopping_patience"] = int(args.epochs)

    data_cfg = base_config["data"]
    attacked = data_cfg["attacked_agents"]
    control = data_cfg["control_agents"]
    k = data_cfg["k_folds"]

    folds = make_stratified_folds(attacked, control, k)
    print(f"Stratified folds (k={k}):")
    for i, fold in enumerate(folds):
        print(f"  fold {i + 1}: {fold}")

    if args.folds is not None:
        fold_indices = [int(x) - 1 for x in args.folds.split(",")]
    else:
        fold_indices = list(range(k))

    # grid[seed][fold_idx] -> auroc
    grid = {seed: [float("nan")] * k for seed in seeds}

    for seed in seeds:
        for fold_idx in fold_indices:
            auroc = run_one(
                base_config=base_config,
                seed=seed,
                fold_idx=fold_idx,
                folds=folds,
                out_dir=args.out_dir,
                fast=args.fast,
            )
            grid[seed][fold_idx] = auroc

    # Grid summary.
    print(f"\n{'=' * 60}")
    print("MULTI-SEED TEST AUROC GRID")
    print(f"{'=' * 60}")
    header = "  seed \\ fold  " + " ".join(f"  f{i + 1}  " for i in range(k)) + "   mean"
    print(header)
    for seed in seeds:
        row_vals = grid[seed]
        finite = [v for v in row_vals if not np.isnan(v)]
        mean = float(np.mean(finite)) if finite else float("nan")
        row = f"  seed={seed:<6} " + " ".join(f"{v:.4f}" for v in row_vals) + f"   {mean:.4f}"
        print(row)

    # Per-fold mean across seeds (if multi-seed).
    if len(seeds) > 1:
        per_fold_means = []
        for fold_idx in range(k):
            col = [grid[s][fold_idx] for s in seeds if not np.isnan(grid[s][fold_idx])]
            per_fold_means.append(float(np.mean(col)) if col else float("nan"))
        print("  fold mean    " + " ".join(f"{v:.4f}" for v in per_fold_means))

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
