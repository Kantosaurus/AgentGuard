"""Standalone single-fold trainer used by the parallel notebook orchestrator.

Trains AgentGuardModel on one (train/val/test) agent split, picks an F1-max
threshold on val, evaluates on test, and writes metrics as JSON.

Usage:
    python scripts/run_fold.py \
        --config-json /tmp/cfg.json \
        --train-agents agent-1,agent-2,... \
        --val-agents   agent-3,... \
        --test-agents  agent-4,... \
        --out-json     /tmp/metrics.json \
        --checkpoint-suffix job0

Each invocation is a self-contained process so the notebook can launch many
concurrently with CUDA_VISIBLE_DEVICES set to pin each to one GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score, average_precision_score, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score,
)
from torch.utils.data import DataLoader

from baselines.run_baselines import pick_threshold
from data.dataset.collate import MixupCollate, agentguard_collate
from data.dataset.telemetry_dataset import AgentGuardDataset
from main import build_model
from sweep.objective import _set_seed
from training.trainer import AgentGuardTrainer


@torch.no_grad()
def _collect_scores(model, loader, device):
    model.eval()
    scores, labels = [], []
    for batch in loader:
        batch = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in batch.items()}
        out = model(batch["stream1"], batch["stream2_seq"], batch["stream2_mask"])
        scores.append(out["anomaly_score"].squeeze(-1).cpu())
        labels.append(batch["label"].cpu())
    return torch.cat(scores).numpy(), torch.cat(labels).numpy().astype(int)


def _metrics_at_threshold(scores, labels, thr):
    preds = (scores >= thr).astype(int)
    if len(np.unique(labels)) < 2:
        auroc = auprc = 0.0
    else:
        auroc = float(roc_auc_score(labels, scores))
        auprc = float(average_precision_score(labels, scores))
    cm = confusion_matrix(labels, preds, labels=[0, 1])
    return {
        "auroc": auroc,
        "auprc": auprc,
        "f1": float(f1_score(labels, preds, zero_division=0)),
        "precision": float(precision_score(labels, preds, zero_division=0)),
        "recall": float(recall_score(labels, preds, zero_division=0)),
        "accuracy": float(accuracy_score(labels, preds)),
        "threshold": float(thr),
        "confusion_matrix": cm.tolist(),
    }


def run_fold(config, train_agents, val_agents, test_agents, checkpoint_suffix):
    _set_seed(42)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    data_cfg = config["data"]
    training_cfg = config["training"]

    train_ds = AgentGuardDataset(
        data_cfg["processed_dir"], train_agents,
        seq_context=data_cfg.get("seq_context", 8), normalize=True,
        augmentation=data_cfg.get("augmentation", "none"),
        augmentation_prob=data_cfg.get("augmentation_prob", 0.0),
    )
    train_mean, train_std = train_ds.get_normalization_stats()

    val_ds = AgentGuardDataset(
        data_cfg["processed_dir"], val_agents,
        seq_context=data_cfg.get("seq_context", 8), normalize=False,
    )
    val_ds.set_normalization_stats(train_mean, train_std)
    val_ds.set_training_mode(False)

    test_ds = AgentGuardDataset(
        data_cfg["processed_dir"], test_agents,
        seq_context=data_cfg.get("seq_context", 8), normalize=False,
    )
    test_ds.set_normalization_stats(train_mean, train_std)
    test_ds.set_training_mode(False)

    collate_fn = MixupCollate(alpha=0.2) if data_cfg.get("augmentation") == "mixup" else agentguard_collate
    loader_kwargs = dict(num_workers=4, pin_memory=True, persistent_workers=True)

    train_loader = DataLoader(
        train_ds, batch_size=training_cfg["batch_size"],
        shuffle=True, collate_fn=collate_fn, **loader_kwargs,
    )
    val_loader = DataLoader(
        val_ds, batch_size=training_cfg["batch_size"],
        shuffle=False, collate_fn=agentguard_collate, **loader_kwargs,
    )
    test_loader = DataLoader(
        test_ds, batch_size=training_cfg["batch_size"],
        shuffle=False, collate_fn=agentguard_collate, **loader_kwargs,
    )

    model = build_model(config)
    ckpt_path = Path(data_cfg["processed_dir"]) / "checkpoints" / f"{checkpoint_suffix}.pt"
    trainer = AgentGuardTrainer(
        model, train_loader, val_loader, config,
        device=device, checkpoint_path=ckpt_path,
    )
    trainer.fit()

    ckpt = torch.load(ckpt_path, weights_only=True)
    model.load_state_dict(ckpt["model_state_dict"])

    val_scores, val_labels = _collect_scores(model, val_loader, device)
    test_scores, test_labels = _collect_scores(model, test_loader, device)

    thr = pick_threshold(val_scores, val_labels)
    return _metrics_at_threshold(test_scores, test_labels, thr)


def _parse_agents(raw):
    return [a.strip() for a in raw.split(",") if a.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config-json", required=True, help="Path to JSON-serialized config dict")
    p.add_argument("--train-agents", required=True, help="comma-separated agent ids")
    p.add_argument("--val-agents", required=True)
    p.add_argument("--test-agents", required=True)
    p.add_argument("--out-json", required=True, help="Where to write metrics JSON")
    p.add_argument("--checkpoint-suffix", required=True, help="Unique suffix for the checkpoint file")
    args = p.parse_args()

    with open(args.config_json) as f:
        config = json.load(f)

    metrics = run_fold(
        config,
        _parse_agents(args.train_agents),
        _parse_agents(args.val_agents),
        _parse_agents(args.test_agents),
        args.checkpoint_suffix,
    )

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_json, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Wrote metrics to {args.out_json}: F1={metrics['f1']:.4f} AUROC={metrics['auroc']:.4f}")


if __name__ == "__main__":
    main()
