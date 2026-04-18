#!/usr/bin/env python3
"""
AgentGuard — CLI Entry Point

Usage:
    python main.py --mode preprocess   # JSONL -> .pt tensors
    python main.py --mode train        # train model (fixed split)
    python main.py --mode eval         # evaluate on test set (fixed split)
    python main.py --mode cv           # k-fold cross-validation at agent level
"""

import argparse
from pathlib import Path

import yaml
import torch
from torch.utils.data import DataLoader

from data.preprocessing import run_preprocessing
from data.dataset.telemetry_dataset import AgentGuardDataset
from data.dataset.collate import agentguard_collate
from models.agentguard import AgentGuardModel
from training.trainer import AgentGuardTrainer


def load_config(path="config.yml"):
    with open(path) as f:
        return yaml.safe_load(f)


def build_model(config):
    model_cfg = config["model"]
    return AgentGuardModel(
        stream1_input_dim=model_cfg["stream1_input_dim"],
        stream2_input_dim=model_cfg["stream2_input_dim"],
        d_model=model_cfg["d_model"],
        latent_dim=model_cfg["latent_dim"],
        mamba_layers=model_cfg["mamba_layers"],
        mamba_state_dim=model_cfg["d_model"],
        transformer_layers=model_cfg["transformer_layers"],
        transformer_heads=model_cfg["transformer_heads"],
        transformer_ff_dim=model_cfg.get("transformer_ff_dim", 512),
        dropout=model_cfg["dropout"],
        max_seq_len=config["data"]["max_seq_len"],
        fusion_strategy=model_cfg.get("fusion_strategy", "cross_attention"),
        cls_head_layers=model_cfg.get("cls_head_layers", 2),
        cls_head_hidden_dim=model_cfg.get("cls_head_hidden_dim", 64),
        cls_head_activation=model_cfg.get("cls_head_activation", "relu"),
        decoder_activation=model_cfg.get("decoder_activation", "relu"),
    )


def build_loaders_from_splits(config, train_agents, val_agents, test_agents=None):
    """Build DataLoaders from explicit agent splits."""
    data_cfg = config["data"]
    training_cfg = config["training"]

    train_ds = AgentGuardDataset(
        data_cfg["processed_dir"], train_agents,
        seq_context=data_cfg["seq_context"], normalize=True,
    )
    train_mean, train_std = train_ds.get_normalization_stats()

    val_ds = AgentGuardDataset(
        data_cfg["processed_dir"], val_agents,
        seq_context=data_cfg["seq_context"], normalize=False,
    )
    val_ds.set_normalization_stats(train_mean, train_std)

    loader_kwargs = dict(
        num_workers=4, pin_memory=True, persistent_workers=True,
    )
    train_loader = DataLoader(
        train_ds, batch_size=training_cfg["batch_size"],
        shuffle=True, collate_fn=agentguard_collate, **loader_kwargs,
    )
    val_loader = DataLoader(
        val_ds, batch_size=training_cfg["batch_size"],
        shuffle=False, collate_fn=agentguard_collate, **loader_kwargs,
    )

    test_loader = None
    if test_agents:
        test_ds = AgentGuardDataset(
            data_cfg["processed_dir"], test_agents,
            seq_context=data_cfg["seq_context"], normalize=False,
        )
        test_ds.set_normalization_stats(train_mean, train_std)
        test_loader = DataLoader(
            test_ds, batch_size=training_cfg["batch_size"],
            shuffle=False, collate_fn=agentguard_collate, **loader_kwargs,
        )
        print(f"Dataset sizes: train={len(train_ds)}, val={len(val_ds)}, test={len(test_ds)}")
    else:
        print(f"Dataset sizes: train={len(train_ds)}, val={len(val_ds)}")

    return train_loader, val_loader, test_loader


# ── preprocess ───────────────────────────────────────────────────────────────

def get_all_agents(data_cfg):
    """Get the full agent list from config, supporting both formats."""
    if "attacked_agents" in data_cfg:
        return data_cfg["attacked_agents"] + data_cfg["control_agents"]
    if "all_agents" in data_cfg:
        return data_cfg["all_agents"]
    return data_cfg.get("train_agents", []) + data_cfg.get("val_agents", []) + data_cfg.get("test_agents", [])


def do_preprocess(config):
    data_cfg = config["data"]
    all_agents = get_all_agents(data_cfg)
    run_preprocessing(
        raw_data_dir=data_cfg["raw_data_dir"],
        processed_dir=data_cfg["processed_dir"],
        date_str=data_cfg["date"],
        agent_ids=all_agents,
        window_size=data_cfg["window_size"],
        max_seq_len=data_cfg["max_seq_len"],
    )


# ── train (fixed split) ─────────────────────────────────────────────────────

def do_train(config):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    model = build_model(config)
    num_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {num_params:,}")

    train_loader, val_loader, _ = build_loaders_from_splits(
        config, config["data"]["train_agents"], config["data"]["val_agents"],
    )

    logger = epoch_csv = None
    log_cfg = config.get("logging", {})
    if log_cfg.get("enabled", False):
        from utils.logging import setup_run_logger, log_config, EpochCSVWriter
        logger, log_path = setup_run_logger("train", config, log_dir=log_cfg.get("log_dir", "logs"))
        log_config(logger, config)
        if log_cfg.get("save_epoch_csv", True):
            epoch_csv = EpochCSVWriter(log_path)

    trainer = AgentGuardTrainer(model, train_loader, val_loader, config, device=device,
                                logger=logger, epoch_csv=epoch_csv)
    try:
        trainer.fit()
    finally:
        if epoch_csv is not None:
            epoch_csv.close()


# ── eval (fixed split) ──────────────────────────────────────────────────────

def do_eval(config):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    model = build_model(config)
    _, _, test_loader = build_loaders_from_splits(
        config,
        config["data"]["train_agents"],
        config["data"]["val_agents"],
        config["data"]["test_agents"],
    )

    logger = None
    log_cfg = config.get("logging", {})
    if log_cfg.get("enabled", False):
        from utils.logging import setup_run_logger, log_config
        logger, _ = setup_run_logger("eval", config, log_dir=log_cfg.get("log_dir", "logs"))
        log_config(logger, config)

    trainer = AgentGuardTrainer(model, None, None, config, device=device, logger=logger)
    trainer.evaluate(test_loader)


# ── k-fold cross-validation ─────────────────────────────────────────────────

# def make_stratified_folds(attacked_agents, control_agents, k):
#     """Split agents into k folds, stratified by group (attacked vs control).
#      original

#     Each fold gets a proportional mix of attacked and control agents.
#     Round-robin assignment within each group ensures balance.
#     With 15 attacked + 5 control across 5 folds: each fold gets 3 attacked + 1 control.
#     """
#     folds = [[] for _ in range(k)]
#     for i, agent in enumerate(attacked_agents):
#         folds[i % k].append(agent)
#     for i, agent in enumerate(control_agents):
#         folds[i % k].append(agent)
#     return folds

def make_stratified_folds(attacked_agents, control_agents, k):
    """
    Tier-aware fold assignment.
    Assumes attacked_agents ordered: Tier1 first (1-5), Tier2 (6-8), Tier3 (9-15).
    """
    tier1 = attacked_agents[:5]   # agents 1-5,  ~100 anomalies each
    tier2 = attacked_agents[5:8]  # agents 6-8,  ~21 anomalies each
    tier3 = attacked_agents[8:]   # agents 9-15, ~13 anomalies each

    folds = [[] for _ in range(k)]

    # Round-robin within each tier independently
    for tier in [tier1, tier2, tier3, control_agents]:
        for i, agent in enumerate(tier):
            folds[i % k].append(agent)

    return folds

def do_cv(config):
    data_cfg = config["data"]
    attacked = data_cfg["attacked_agents"]
    control = data_cfg["control_agents"]
    k = data_cfg["k_folds"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    print(f"Running {k}-fold stratified agent-level cross-validation")
    print(f"  Attacked agents: {len(attacked)}, Control agents: {len(control)}\n")

    folds = make_stratified_folds(attacked, control, k)

    # Set up logging for the entire CV run
    cv_logger = None
    log_cfg = config.get("logging", {})
    if log_cfg.get("enabled", False):
        from utils.logging import setup_run_logger, log_config
        cv_logger, _ = setup_run_logger("cv", config, log_dir=log_cfg.get("log_dir", "logs"))
        log_config(cv_logger, config)

    fold_results = []

    for fold_idx in range(k):
        print(f"\n{'='*60}")
        print(f"FOLD {fold_idx + 1}/{k}")
        print(f"{'='*60}")
        if cv_logger:
            cv_logger.info(f"\nFOLD {fold_idx + 1}/{k}")

        # Test fold = current fold
        test_agents = folds[fold_idx]
        # Val fold = next fold (wrapping around)
        val_agents = folds[(fold_idx + 1) % k]
        # Train folds = everything else
        train_agents = []
        for j in range(k):
            if j != fold_idx and j != (fold_idx + 1) % k:
                train_agents.extend(folds[j])

        print(f"  Train: {train_agents}")
        print(f"  Val:   {val_agents}")
        print(f"  Test:  {test_agents}\n")

        # Fresh model per fold
        model = build_model(config)
        if fold_idx == 0:
            num_params = sum(p.numel() for p in model.parameters())
            print(f"Model parameters: {num_params:,}\n")

        train_loader, val_loader, test_loader = build_loaders_from_splits(
            config, train_agents, val_agents, test_agents,
        )

        # Per-fold checkpoint
        checkpoint_dir = Path(data_cfg["processed_dir"]) / "checkpoints"
        checkpoint_path = checkpoint_dir / f"best_model_fold{fold_idx + 1}.pt"

        # Per-fold epoch CSV
        epoch_csv = None
        if log_cfg.get("enabled", False) and log_cfg.get("save_epoch_csv", True):
            from utils.logging import EpochCSVWriter, setup_run_logger
            fold_logger, fold_log_path = setup_run_logger(
                "cv", config, log_dir=log_cfg.get("log_dir", "logs"),
                trial_number=fold_idx + 1,
            )
            epoch_csv = EpochCSVWriter(fold_log_path)
        else:
            fold_logger = None

        trainer = AgentGuardTrainer(
            model, train_loader, val_loader, config,
            device=device, checkpoint_path=checkpoint_path,
            logger=fold_logger or cv_logger, epoch_csv=epoch_csv,
        )
        try:
            trainer.fit()
        finally:
            if epoch_csv is not None:
                epoch_csv.close()

        # Evaluate on test fold
        test_losses, test_metrics = trainer.evaluate(test_loader)
        fold_results.append({
            "fold": fold_idx + 1,
            "test_agents": test_agents,
            "val_agents": val_agents,
            "test_loss": test_losses["total"],
            "test_auroc": test_metrics["auroc"],
            "test_auprc": test_metrics["auprc"],
            "test_f1": test_metrics["f1"],
            "test_precision": test_metrics["precision"],
            "test_recall": test_metrics["recall"],
            "test_recon": test_losses["recon"],
            "test_contrastive": test_losses["contrastive"],
            "test_temporal": test_losses["temporal"],
        })

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"{k}-FOLD CROSS-VALIDATION SUMMARY")
    print(f"{'='*60}")

    aurocs = [r["test_auroc"] for r in fold_results]
    losses = [r["test_loss"] for r in fold_results]

    for r in fold_results:
        summary_line = (f"  Fold {r['fold']}: AUROC={r['test_auroc']:.4f}  "
                        f"Loss={r['test_loss']:.4f}  "
                        f"Test agents: {r['test_agents']}")
        print(summary_line)
        if cv_logger:
            cv_logger.info(summary_line)

    mean_auroc = sum(aurocs) / len(aurocs)
    std_auroc = (sum((a - mean_auroc) ** 2 for a in aurocs) / len(aurocs)) ** 0.5
    mean_loss = sum(losses) / len(losses)
    std_loss = (sum((l - mean_loss) ** 2 for l in losses) / len(losses)) ** 0.5

    print(f"\n  Mean AUROC: {mean_auroc:.4f} +/- {std_auroc:.4f}")
    print(f"  Mean Loss:  {mean_loss:.4f} +/- {std_loss:.4f}")
    print(f"{'='*60}")

    if cv_logger:
        cv_logger.info(f"\n  Mean AUROC: {mean_auroc:.4f} +/- {std_auroc:.4f}")
        cv_logger.info(f"  Mean Loss:  {mean_loss:.4f} +/- {std_loss:.4f}")
        cv_logger.info("=" * 60)

    return fold_results


def evaluate_per_agent(scores, labels, agent_ids, threshold=0.5):
    import numpy as np
    from collections import defaultdict
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
    )
    """
    Compute metrics per agent.

    Args:
        scores: np.array of anomaly scores
        labels: np.array of true labels
        agent_ids: list of agent IDs (strings)
        threshold: threshold for binary prediction

    Returns:
        dict mapping agent_id -> metrics dict
    """
    # Convert scores to binary predictions
    preds = (scores >= threshold).astype(int)

    # Group by agent
    agent_data = defaultdict(lambda: {"labels": [], "preds": []})
    for agent, label, pred in zip(agent_ids, labels, preds):
        agent_data[agent]["labels"].append(label)
        agent_data[agent]["preds"].append(pred)

    # Compute metrics per agent
    agent_metrics = {}
    for agent, data in agent_data.items():
        y_true = np.array(data["labels"])
        y_pred = np.array(data["preds"])
        cm = confusion_matrix(y_true, y_pred)
        metrics = {
            "num_samples": len(y_true),
            "num_normal": int((y_true == 0).sum()),
            "num_anomaly": int((y_true == 1).sum()),
            "accuracy": accuracy_score(y_true, y_pred),
            "precision": precision_score(y_true, y_pred, zero_division=0),
            "recall": recall_score(y_true, y_pred, zero_division=0),
            "f1": f1_score(y_true, y_pred, zero_division=0),
            "confusion_matrix": cm,
        }
        agent_metrics[agent] = metrics

    return agent_metrics


def test_trained_model(test_config, weights_config):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    model = build_model(weights_config)

    ckpt_path = test_config["inference"]["checkpoint_path"]
    checkpoint = torch.load(ckpt_path, map_location=device)

    if "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model.load_state_dict(checkpoint)

    model.to(device)
    model.eval()

    print(f"Loaded weights from: {ckpt_path}")

    data_cfg = test_config["data"]

    test_ds = AgentGuardDataset(
        data_cfg["processed_dir"],
        data_cfg["test_agents"],
        seq_context=weights_config["data"]["seq_context"],
        normalize=False,
    )

    # Get Normalization Stats from training agent
    train_agents = test_config["data"]["train_agents"]
    train_ds = AgentGuardDataset(
        data_cfg["processed_dir"],
        train_agents,
        seq_context=weights_config["data"]["seq_context"],
        normalize=True,  # we want to compute mean/std
    )

    # get mean and std from the training dataset
    train_mean, train_std = train_ds.get_normalization_stats()
    test_ds.set_normalization_stats(train_mean, train_std)

    test_loader = DataLoader(
        test_ds,
        batch_size=test_config["inference"].get("batch_size", 32),
        shuffle=False,
        collate_fn=agentguard_collate,
    )

    print(f"Test samples: {len(test_ds)}")

    # -----------------------------
    # 5. Run inference
    # -----------------------------
    all_scores = []
    all_labels = []
    all_agent_ids = []

    with torch.no_grad():
        for batch in test_loader:
            # Move only tensors to device
            batch = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in batch.items()}
            outputs = model(batch["stream1"], batch["stream2_seq"], batch["stream2_mask"])
            all_scores.append(outputs["anomaly_score"].squeeze(-1).cpu())
            all_labels.append(batch["label"].cpu())
            all_agent_ids.extend(batch["agent_id"])

    all_scores = torch.cat(all_scores).numpy()
    all_labels = torch.cat(all_labels).numpy()

    print("Inference complete")

    return all_scores, all_labels, all_agent_ids


def write_test_results_md(per_agent_metrics, overall_metrics, output_file="test_results.md"):
    """
    Write per-agent and overall test results into a Markdown file.

    Args:
        per_agent_metrics (dict): Dictionary of per-agent metrics.
        overall_metrics (dict): Dictionary of overall metrics.
        output_file (str): Path to the output Markdown file.
    """
    import os
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Test Results\n\n")

        # Per-agent metrics
        f.write("## Per-Agent Performance\n\n")
        for agent, metrics in per_agent_metrics.items():
            f.write(f"### Agent: {agent}\n")
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            for k, v in metrics.items():
                if k == "confusion_matrix":
                    cm = v.tolist() if hasattr(v, "tolist") else v
                    cm_str = f"<pre>{cm}</pre>"
                    f.write(f"| {k} | {cm_str} |\n")
                else:
                    f.write(f"| {k} | {v} |\n")
            f.write("\n")

        # Overall metrics
        f.write("## Overall Performance\n\n")
        f.write("| Metric | Value |\n")
        f.write("|--------|-------|\n")
        for k, v in overall_metrics.items():
            if k == "confusion_matrix":
                cm = v.tolist() if hasattr(v, "tolist") else v
                cm_str = f"<pre>{cm}</pre>"
                f.write(f"| {k} | {cm_str} |\n")
            else:
                f.write(f"| {k} | {v} |\n")

    print(f"Results written to {os.path.abspath(output_file)}")

def set_global_seed(seed: int = 42):
    import random
    import numpy as np
    # Python
    random.seed(seed)

    # NumPy
    np.random.seed(seed)

    # PyTorch
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

    print(f"Global seed set to {seed}")

# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    set_global_seed(42)
    parser = argparse.ArgumentParser(description="AgentGuard training pipeline")
    parser.add_argument("--mode", required=True,
                        choices=["preprocess", "train", "eval", "cv", "test"],
                        help="Pipeline mode: preprocess, train, eval, or cv")
    parser.add_argument("--config", default="config.yml", help="Path to config file")
    parser.add_argument("--weights_config",
        default="config.yml",
        help="Path to training config (for model architecture)"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    if args.mode == "preprocess":
        do_preprocess(config)
    elif args.mode == "train":
        do_train(config)
    elif args.mode == "eval":
        do_eval(config)
    elif args.mode == "cv":
        do_cv(config)
    
    elif args.mode == "test":
        if args.weights_config is None:
            raise ValueError("You must provide --weights_config for test mode")

        test_config = config
        weights_config = load_config(args.weights_config)

        # Run inference
        scores, labels, agent_ids = test_trained_model(test_config, weights_config)

        per_agent_metrics = evaluate_per_agent(scores, labels, agent_ids, threshold=0.5)

        threshold = 0.5
        overall_preds = (scores >= threshold).astype(int)
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix
        overall_metrics = {
            "num_samples": len(labels),
            "num_normal": int((labels == 0).sum()),
            "num_anomaly": int((labels == 1).sum()),
            "accuracy": accuracy_score(labels, overall_preds),
            "precision": precision_score(labels, overall_preds, zero_division=0),
            "recall": recall_score(labels, overall_preds, zero_division=0),
            "f1": f1_score(labels, overall_preds, zero_division=0),
            "confusion_matrix": confusion_matrix(labels, overall_preds),
        }
        output_file="results.md"
        write_test_results_md(per_agent_metrics, overall_metrics, output_file=output_file)

        print(f"Saved Results in Markdown file: {output_file}")


if __name__ == "__main__":
    main()
