"""
AgentGuard — Ensemble Inference

Trains top-K configs on full training set, then combines predictions
via averaging, weighted averaging, and majority voting.

Usage:
    python -m sweep.ensemble --top-k 3 --config config.yml
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

import yaml

from data.dataset.telemetry_dataset import AgentGuardDataset
from data.dataset.collate import agentguard_collate
from main import build_model
from sweep.config_override import override_config
from sweep.objective import _set_seed
from training.trainer import AgentGuardTrainer


RESULTS_DIR = Path("sweep/results")


def _load_top_configs(top_k):
    """Load top-K configs from Phase 4 results (or Phase 3 fallback)."""
    p4_path = RESULTS_DIR / "phase4_results.json"
    if p4_path.exists():
        with open(p4_path) as f:
            results = json.load(f)
        return results[:top_k]

    # Fallback: load from Phase 3 study
    import optuna
    storage = f"sqlite:///{RESULTS_DIR / 'optuna.db'}"
    study = optuna.load_study(study_name="phase3_loss_data", storage=storage)
    sorted_trials = sorted(study.trials, key=lambda t: t.value or 0, reverse=True)
    return [{"params": t.params, "mean_auroc": t.value} for t in sorted_trials[:top_k]]


def train_and_collect(base_config, configs, train_agents, test_agents, device):
    """Train each config on train set, collect test predictions."""
    all_predictions = []
    val_aurocs = []

    for i, cfg_info in enumerate(configs):
        print(f"\n--- Training model {i+1}/{len(configs)} ---")
        _set_seed(42)

        config = override_config(base_config, cfg_info["params"])
        data_cfg = config["data"]
        training_cfg = config["training"]

        # Use all train agents, split off last 3 for validation
        val_split = train_agents[-3:]
        train_split = train_agents[:-3]

        train_ds = AgentGuardDataset(
            data_cfg["processed_dir"], train_split,
            seq_context=data_cfg.get("seq_context", 8), normalize=True,
        )
        train_mean, train_std = train_ds.get_normalization_stats()

        val_ds = AgentGuardDataset(
            data_cfg["processed_dir"], val_split,
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

        train_loader = DataLoader(
            train_ds, batch_size=training_cfg["batch_size"],
            shuffle=True, collate_fn=agentguard_collate,
        )
        val_loader = DataLoader(
            val_ds, batch_size=training_cfg["batch_size"],
            shuffle=False, collate_fn=agentguard_collate,
        )
        test_loader = DataLoader(
            test_ds, batch_size=training_cfg["batch_size"],
            shuffle=False, collate_fn=agentguard_collate,
        )

        model = build_model(config)
        ckpt_path = Path(data_cfg["processed_dir"]) / "checkpoints" / f"ensemble_model_{i}.pt"

        trainer = AgentGuardTrainer(
            model, train_loader, val_loader, config,
            device=device, checkpoint_path=ckpt_path,
        )
        metrics = trainer.fit()
        val_aurocs.append(metrics.get("auroc", 0.0))

        # Collect test predictions
        _, test_metrics = trainer.evaluate(test_loader)
        print(f"  Individual test AUROC: {test_metrics['auroc']:.4f}")

        # Get raw scores
        model.eval()
        if ckpt_path.exists():
            checkpoint = torch.load(ckpt_path, weights_only=True)
            model.load_state_dict(checkpoint["model_state_dict"])

        scores = []
        labels = []
        with torch.no_grad():
            for batch in test_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                outputs = model(batch["stream1"], batch["stream2_seq"], batch["stream2_mask"])
                scores.append(outputs["anomaly_score"].squeeze(-1).cpu())
                labels.append(batch["label"].cpu())

        all_predictions.append(torch.cat(scores).numpy())
        if i == 0:
            test_labels = torch.cat(labels).numpy().astype(int)

    return all_predictions, test_labels, val_aurocs


def ensemble_evaluate(predictions, labels, val_aurocs):
    """Evaluate ensemble strategies: average, weighted average, majority vote
    with threshold tuned for best F1.
    """
    from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, precision_recall_curve
    import numpy as np

    def find_best_threshold(scores, labels):
        """Find threshold that maximizes F1 score"""
        precision, recall, thresholds = precision_recall_curve(labels, scores)
        f1_scores = 2 * (precision * recall) / (precision + recall + 1e-8)
        best_idx = np.argmax(f1_scores)
        best_thresh = thresholds[best_idx] if best_idx < len(thresholds) else 0.5
        best_f1 = f1_scores[best_idx]
        return best_thresh, best_f1

    preds_stack = np.stack(predictions)  # [K, N]
    results = {}

    # ----- Simple averaging -----
    avg_scores = preds_stack.mean(axis=0)
    best_thresh, best_f1 = find_best_threshold(avg_scores, labels)
    avg_preds = (avg_scores >= best_thresh).astype(int)
    results["average"] = {
        "auroc": float(roc_auc_score(labels, avg_scores)),
        "auprc": float(average_precision_score(labels, avg_scores)),
        "f1": float(best_f1),
        "threshold": float(best_thresh),
    }

    # ----- Weighted averaging (by validation AUROC) -----
    weights = np.array(val_aurocs)
    weights = weights / weights.sum()
    weighted_scores = (preds_stack * weights[:, None]).sum(axis=0)
    best_thresh, best_f1 = find_best_threshold(weighted_scores, labels)
    weighted_preds = (weighted_scores >= best_thresh).astype(int)
    results["weighted_average"] = {
        "auroc": float(roc_auc_score(labels, weighted_scores)),
        "auprc": float(average_precision_score(labels, weighted_scores)),
        "f1": float(best_f1),
        "threshold": float(best_thresh),
    }

    # ----- Majority voting -----
    binary_preds = (preds_stack >= 0.5).astype(int)  # individual model votes
    majority_scores = binary_preds.mean(axis=0)     # fraction of models voting positive
    best_thresh, best_f1 = find_best_threshold(majority_scores, labels)
    majority_preds = (majority_scores >= best_thresh).astype(int)
    results["majority_vote"] = {
        "f1": float(best_f1),
        "threshold": float(best_thresh),
    }

    return results


def main():
    parser = argparse.ArgumentParser(description="AgentGuard ensemble evaluation")
    parser.add_argument("--top-k", type=int, default=3, help="Number of top configs")
    parser.add_argument("--config", default="config.yml", help="Base config path")
    args = parser.parse_args()

    with open(args.config) as f:
        base_config = yaml.safe_load(f)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    configs = _load_top_configs(args.top_k)
    data_cfg = base_config["data"]

    train_agents = data_cfg["train_agents"]
    test_agents = data_cfg["test_agents"]

    print(f"Ensemble with top-{args.top_k} configs on device={device}")

    predictions, labels, val_aurocs = train_and_collect(
        base_config, configs, train_agents, test_agents, device,
    )

    results = ensemble_evaluate(predictions, labels, val_aurocs)

    print(f"\n{'='*60}")
    print("ENSEMBLE RESULTS")
    print(f"{'='*60}")
    for strategy, metrics in results.items():
        print(f"  {strategy}: {metrics}")

    results_path = RESULTS_DIR / "ensemble_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {results_path}")


if __name__ == "__main__":
    main()
