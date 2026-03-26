"""
AgentGuard — Training Loop

Trainer class with configurable optimizer/scheduler, gradient clipping,
early stopping, checkpointing, comprehensive metrics, and Optuna pruning.
"""

import os
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.optim.lr_scheduler import CosineAnnealingLR, ReduceLROnPlateau, OneCycleLR
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score, precision_score, recall_score

from training.losses import HybridLoss


class AgentGuardTrainer:
    """Training loop for the AgentGuard model."""

    def __init__(self, model, train_loader, val_loader, config, device="cpu",
                 checkpoint_path=None, trial=None, logger=None, epoch_csv=None):
        self.model = model.to(device)
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.device = device
        self.config = config
        self.trial = trial
        self.logger = logger
        self.epoch_csv = epoch_csv

        training_cfg = config["training"]

        self.criterion = HybridLoss(
            lambda_recon=training_cfg["lambda_recon"],
            lambda_contrastive=training_cfg["lambda_contrastive"],
            lambda_temporal=training_cfg["lambda_temporal"],
            class_weight_ratio=config.get("data", {}).get("class_weight_ratio", 1.0),
        )

        # Optimizer selection
        lr = training_cfg["lr"]
        opt_name = training_cfg.get("optimizer", "adam")
        if opt_name == "adamw":
            wd = training_cfg.get("weight_decay", 0.0)
            self.optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
        else:
            self.optimizer = torch.optim.Adam(model.parameters(), lr=lr)

        # Scheduler selection
        sched_name = training_cfg.get("scheduler", "cosine")
        self.step_per_batch = False
        if sched_name == "plateau":
            self.scheduler = ReduceLROnPlateau(self.optimizer, mode="min", patience=5, factor=0.5)
        elif sched_name == "onecycle":
            if train_loader is not None:
                total_steps = training_cfg["epochs"] * len(train_loader)
            else:
                total_steps = training_cfg["epochs"]
            self.scheduler = OneCycleLR(self.optimizer, max_lr=lr, total_steps=total_steps)
            self.step_per_batch = True
        else:  # cosine (default)
            self.scheduler = CosineAnnealingLR(self.optimizer, T_max=training_cfg["epochs"])

        self.sched_name = sched_name
        self.max_grad_norm = training_cfg.get("max_grad_norm", 1.0)

        self.epochs = training_cfg["epochs"]
        self.patience = training_cfg["early_stopping_patience"]

        if checkpoint_path is not None:
            self.checkpoint_path = Path(checkpoint_path)
        else:
            self.checkpoint_path = Path(config["data"]["processed_dir"]) / "checkpoints" / "best_model.pt"
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, msg):
        """Write to file logger if one is attached."""
        if self.logger is not None:
            self.logger.info(msg)

    def train_epoch(self):
        """Run one training epoch. Returns average loss dict."""
        self.model.train()
        total_losses = {"recon": 0, "contrastive": 0, "temporal": 0, "total": 0}
        num_batches = 0

        for batch in self.train_loader:
            batch = {k: v.to(self.device) for k, v in batch.items()}

            outputs = self.model(
                batch["stream1"], batch["stream2_seq"], batch["stream2_mask"]
            )

            loss, loss_dict = self.criterion(outputs, batch)

            self.optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
            self.optimizer.step()

            if self.step_per_batch:
                self.scheduler.step()

            for k in total_losses:
                total_losses[k] += loss_dict[k]
            num_batches += 1

        return {k: v / max(num_batches, 1) for k, v in total_losses.items()}

    @torch.no_grad()
    def validate(self):
        """Run validation. Returns (avg_loss_dict, auroc)."""
        self.model.eval()
        total_losses = {"recon": 0, "contrastive": 0, "temporal": 0, "total": 0}
        num_batches = 0

        all_scores = []
        all_labels = []

        for batch in self.val_loader:
            batch = {k: v.to(self.device) for k, v in batch.items()}

            outputs = self.model(
                batch["stream1"], batch["stream2_seq"], batch["stream2_mask"]
            )

            _, loss_dict = self.criterion(outputs, batch)

            for k in total_losses:
                total_losses[k] += loss_dict[k]
            num_batches += 1

            all_scores.append(outputs["anomaly_score"].squeeze(-1).cpu())
            all_labels.append(batch["label"].cpu())

        avg_losses = {k: v / max(num_batches, 1) for k, v in total_losses.items()}

        # Compute metrics
        scores = torch.cat(all_scores)
        labels = torch.cat(all_labels)
        metrics = self._compute_metrics(scores, labels)

        return avg_losses, metrics

    @staticmethod
    def _compute_metrics(scores, labels):
        """Compute comprehensive metrics using sklearn.

        Returns dict with: auroc, auprc, f1, precision, recall.
        """
        scores_np = scores.numpy()
        labels_np = labels.numpy().astype(int)

        # Handle single-class edge case
        if len(np.unique(labels_np)) < 2:
            return {"auroc": 0.0, "auprc": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0}

        preds = (scores_np >= 0.5).astype(int)

        return {
            "auroc": float(roc_auc_score(labels_np, scores_np)),
            "auprc": float(average_precision_score(labels_np, scores_np)),
            "f1": float(f1_score(labels_np, preds, zero_division=0)),
            "precision": float(precision_score(labels_np, preds, zero_division=0)),
            "recall": float(recall_score(labels_np, preds, zero_division=0)),
        }

    def fit(self):
        """Full training loop with early stopping, checkpointing, and Optuna pruning."""
        best_val_loss = float("inf")
        best_metrics = {"auroc": 0.0, "auprc": 0.0, "f1": 0.0, "precision": 0.0, "recall": 0.0}
        epochs_without_improvement = 0
        best_f1 = 0.0
        best_auroc = 0.0
        for epoch in range(1, self.epochs + 1):
            train_losses = self.train_epoch()
            val_losses, metrics = self.validate()

            # Scheduler step (per-epoch schedulers only; per-batch handled in train_epoch)
            if not self.step_per_batch:
                if self.sched_name == "plateau":
                    self.scheduler.step(val_losses["total"])
                else:
                    self.scheduler.step()

            lr = self.optimizer.param_groups[0]["lr"]

            epoch_msg = (
                f"Epoch {epoch:3d}/{self.epochs} | "
                f"Train: {train_losses['total']:.4f} "
                f"(R={train_losses['recon']:.4f} C={train_losses['contrastive']:.4f} T={train_losses['temporal']:.4f}) | "
                f"Val: {val_losses['total']:.4f} | "
                f"AUROC: {metrics['auroc']:.4f} AUPRC: {metrics['auprc']:.4f} "
                f"F1: {metrics['f1']:.4f} P: {metrics['precision']:.4f} R: {metrics['recall']:.4f} | "
                f"LR: {lr:.6f}"
            )
            print(epoch_msg)
            self._log(epoch_msg)
            if self.epoch_csv is not None:
                self.epoch_csv.write_row(epoch, train_losses, val_losses, metrics, lr)

            # Optuna pruning
            if self.trial is not None:
                self.trial.report(metrics["auroc"], epoch)
                if self.trial.should_prune():
                    import optuna
                    raise optuna.TrialPruned()

            # Check for improvement
            current_f1 = metrics["f1"]
            current_auroc = metrics["auroc"]
            if (current_f1 > best_f1) or (current_f1 == best_f1 and current_auroc > best_auroc):
                best_f1 = current_f1
                best_auroc = current_auroc
                # best_val_loss = val_losses["total"]
                best_metrics = metrics.copy()
                epochs_without_improvement = 0

                # Save checkpoint
                torch.save({
                    "epoch": epoch,
                    "model_state_dict": self.model.state_dict(),
                    "optimizer_state_dict": self.optimizer.state_dict(),
                    "val_loss": best_val_loss,
                    "metrics": best_metrics,
                }, self.checkpoint_path)
                # save_msg = f"  -> Saved best model (val_loss={best_val_loss:.4f}, auroc={best_metrics['auroc']:.4f})"
                save_msg = f"  -> Saved best model (F1={best_metrics['f1']:.4f})"
                print(save_msg)
                self._log(save_msg)
            else:
                epochs_without_improvement += 1
                if epochs_without_improvement >= self.patience:
                    es_msg = (f"\nEarly stopping at epoch {epoch} "
                              f"(no improvement for {self.patience} epochs)")
                    print(es_msg)
                    self._log(es_msg)
                    break

        # print(f"\nTraining complete. Best val_loss: {best_val_loss:.4f}")
        print(f"\nTraining complete. Best F1: {best_metrics['f1']:.4f}")
        print(f"Best metrics: {best_metrics}")
        print(f"Best model saved to: {self.checkpoint_path}")

        if self.logger is not None:
            from utils.logging import log_results
            log_results(self.logger, best_metrics, best_val_loss)

        return best_metrics

    @torch.no_grad()
    def evaluate(self, test_loader):
        """Evaluate on test set. Returns (loss_dict, metrics_dict)."""
        # Load best model
        if self.checkpoint_path.exists():
            checkpoint = torch.load(self.checkpoint_path, weights_only=True)
            self.model.load_state_dict(checkpoint["model_state_dict"])
            print(f"Loaded best model from epoch {checkpoint['epoch']}")

        self.model.eval()
        total_losses = {"recon": 0, "contrastive": 0, "temporal": 0, "total": 0}
        num_batches = 0
        all_scores = []
        all_labels = []

        for batch in test_loader:
            batch = {k: v.to(self.device) for k, v in batch.items()}
            outputs = self.model(
                batch["stream1"], batch["stream2_seq"], batch["stream2_mask"]
            )
            _, loss_dict = self.criterion(outputs, batch)
            for k in total_losses:
                total_losses[k] += loss_dict[k]
            num_batches += 1
            all_scores.append(outputs["anomaly_score"].squeeze(-1).cpu())
            all_labels.append(batch["label"].cpu())

        avg_losses = {k: v / max(num_batches, 1) for k, v in total_losses.items()}
        scores = torch.cat(all_scores)
        labels = torch.cat(all_labels)
        metrics = self._compute_metrics(scores, labels)

        print(f"\n{'='*60}")
        print(f"Test Results:")
        print(f"  Loss:  {avg_losses['total']:.4f} "
              f"(R={avg_losses['recon']:.4f} C={avg_losses['contrastive']:.4f} T={avg_losses['temporal']:.4f})")
        print(f"  AUROC:     {metrics['auroc']:.4f}")
        print(f"  AUPRC:     {metrics['auprc']:.4f}")
        print(f"  F1:        {metrics['f1']:.4f}")
        print(f"  Precision: {metrics['precision']:.4f}")
        print(f"  Recall:    {metrics['recall']:.4f}")
        print(f"  Samples: {len(labels)} (anomalous={labels.sum().item()}, normal={(labels==0).sum().item()})")
        print(f"{'='*60}")

        if self.logger is not None:
            from utils.logging import log_test_results
            log_test_results(
                self.logger, avg_losses, metrics,
                n_samples=len(labels), n_anomalous=int(labels.sum().item()),
            )

        return avg_losses, metrics
