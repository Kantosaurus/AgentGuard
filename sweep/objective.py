"""
AgentGuard — Optuna Objective Function

Creates objective functions for each phase of hyperparameter search.
Supports single-split and k-fold cross-validation evaluation.
"""

import os
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from sweep.config_override import override_config
from sweep.search_space import (
    suggest_phase1_architecture,
    suggest_phase2_training,
    suggest_phase3_loss_and_data,
)


def _set_seed(seed=42):
    """Set random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        # Disable TF32 on Hopper/Ada — TF32's reduced mantissa can push the
        # Mamba SSM prefix-scan into NaN territory, triggering a device-side
        # BCELoss assertion. Keeps behaviour consistent with main.set_global_seed.
        try:
            torch.set_float32_matmul_precision("highest")
        except Exception:
            pass
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False


def _run_single_fold(config, train_agents, val_agents, device, trial=None,
                     checkpoint_suffix="sweep", logger=None, epoch_csv=None):
    """Train and evaluate a single fold. Returns val AUROC."""
    from data.dataset.telemetry_dataset import AgentGuardDataset
    from data.dataset.collate import agentguard_collate, MixupCollate
    from main import build_model
    from training.trainer import AgentGuardTrainer

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

    # Choose collate function
    aug = data_cfg.get("augmentation", "none")
    if aug == "mixup":
        collate_fn = MixupCollate(alpha=0.2)
    else:
        collate_fn = agentguard_collate

    loader_kwargs = dict(
        num_workers=4, pin_memory=True, persistent_workers=True,
    )
    train_loader = DataLoader(
        train_ds, batch_size=training_cfg["batch_size"],
        shuffle=True, collate_fn=collate_fn, **loader_kwargs,
    )
    val_loader = DataLoader(
        val_ds, batch_size=training_cfg["batch_size"],
        shuffle=False, collate_fn=agentguard_collate, **loader_kwargs,
    )

    model = build_model(config)
    checkpoint_path = Path(data_cfg["processed_dir"]) / "checkpoints" / f"best_{checkpoint_suffix}.pt"

    trainer = AgentGuardTrainer(
        model, train_loader, val_loader, config,
        device=device, checkpoint_path=checkpoint_path, trial=trial,
        logger=logger, epoch_csv=epoch_csv,
    )
    metrics = trainer.fit()
    # return metrics.get("auroc", 0.0)
    return metrics.get("f1", 0.0)


def create_objective(base_config, phase, best_params=None, n_folds=0):
    """Return an Optuna objective function for the given phase.

    Args:
        base_config: Base config dict.
        phase: 1 (architecture), 2 (training), 3 (loss+data).
        best_params: Locked overrides from previous phases.
        n_folds: If > 0, run k-fold CV and return mean AUROC.
    """
    if best_params is None:
        best_params = {}

    def objective(trial):
        # Suggest hyperparameters
        if phase == 1:
            overrides = suggest_phase1_architecture(trial)
        elif phase == 2:
            overrides = suggest_phase2_training(trial, best_params)
        elif phase == 3:
            overrides = suggest_phase3_loss_and_data(trial, best_params)
        else:
            raise ValueError(f"Unknown phase: {phase}")

        config = override_config(base_config, overrides)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _set_seed(42)

        # Per-trial logging
        trial_logger = None
        trial_csv = None
        log_cfg = config.get("logging", {})
        if log_cfg.get("enabled", False):
            from utils.logging import setup_run_logger, log_config, EpochCSVWriter
            trial_logger, trial_log_path = setup_run_logger(
                "sweep", config, log_dir=log_cfg.get("log_dir", "logs"),
                trial_number=trial.number, phase=phase,
            )
            log_config(trial_logger, config)
            if log_cfg.get("save_epoch_csv", True):
                trial_csv = EpochCSVWriter(trial_log_path)

        try:
            if n_folds > 0:
                # K-fold CV
                from main import make_stratified_folds
                data_cfg = config["data"]
                attacked = data_cfg["attacked_agents"]
                control = data_cfg["control_agents"]
                folds = make_stratified_folds(attacked, control, n_folds)

                aurocs = []
                for fold_idx in range(n_folds):
                    test_agents = folds[fold_idx]
                    val_agents = folds[(fold_idx + 1) % n_folds]
                    train_agents = []
                    for j in range(n_folds):
                        if j != fold_idx and j != (fold_idx + 1) % n_folds:
                            train_agents.extend(folds[j])

                    f1 = _run_single_fold(
                        config, train_agents, val_agents, device,
                        trial=trial if fold_idx == 0 else None,
                        checkpoint_suffix=f"sweep_pid{os.getpid()}_f{fold_idx}",
                        logger=trial_logger, epoch_csv=trial_csv,
                    )
                    aurocs.append(f1)

                return float(np.mean(f1))
                #     auroc = _run_single_fold(
                #         config, train_agents, val_agents, device,
                #         trial=trial if fold_idx == 0 else None,
                #         checkpoint_suffix=f"sweep_f{fold_idx}",
                #         logger=trial_logger, epoch_csv=trial_csv,
                #     )
                #     aurocs.append(auroc)

                # return float(np.mean(aurocs))
            else:
                # Single split
                data_cfg = config["data"]
                return _run_single_fold(
                    config, data_cfg["train_agents"], data_cfg["val_agents"],
                    device, trial=trial,
                    checkpoint_suffix=f"sweep_pid{os.getpid()}",
                    logger=trial_logger, epoch_csv=trial_csv,
                )

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                print(f"Trial {trial.number} OOM — returning 0.0")
                return 0.0
            raise
        finally:
            if trial_csv is not None:
                trial_csv.close()

    return objective
