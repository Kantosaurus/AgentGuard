"""
AgentGuard — Run Logger

Logs configuration, per-epoch metrics, and final results to disk.
Each run produces a .log file (human-readable) and optionally an _epochs.csv
file (machine-readable) for later plotting.
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path


def _flatten_dict(d, prefix=""):
    """Flatten nested dict to dot-notation keys, skipping lists."""
    flat = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_dict(value, full_key))
        elif not isinstance(value, list):
            flat[full_key] = value
    return flat


def setup_run_logger(mode, config, log_dir="logs", trial_number=None, phase=None):
    """Create a file logger for a single run.

    Args:
        mode: "train", "eval", "cv", or "sweep".
        config: Full config dict (used only for the timestamp).
        log_dir: Directory to write log files into.
        trial_number: If set, include trial number in the filename.
        phase: If set, include phase label in the filename.

    Returns:
        (logger, log_path) — the Logger instance and the Path to its file.
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    parts = []
    if phase is not None:
        parts.append(f"{mode}_phase{phase}")
    else:
        parts.append(mode)
    if trial_number is not None:
        parts.append(f"t{trial_number:03d}")
    parts.append(ts)

    basename = "_".join(parts)
    log_path = Path(log_dir) / f"{basename}.log"

    logger = logging.getLogger(f"agentguard.{basename}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Avoid duplicate handlers on repeated calls
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(fh)

    # Write header
    label = mode
    if phase is not None:
        label = f"{mode} phase{phase}"
    if trial_number is not None:
        label += f" trial {trial_number}"
    logger.info("=" * 60)
    logger.info(f"AgentGuard Run: {label} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    return logger, log_path


def log_config(logger, config):
    """Write the flattened config as a [CONFIG] section."""
    flat = _flatten_dict(config)
    logger.info("")
    logger.info("[CONFIG]")
    max_key_len = max(len(k) for k in flat) if flat else 0
    for key in sorted(flat):
        logger.info(f"  {key:<{max_key_len + 2}}{flat[key]}")
    logger.info("")


def log_epoch(logger, epoch, total_epochs, train_losses, val_losses, metrics, lr):
    """Write one epoch summary line."""
    logger.info(
        f"Epoch {epoch:3d}/{total_epochs} | "
        f"Train: {train_losses['total']:.4f} "
        f"(R={train_losses['recon']:.4f} C={train_losses['contrastive']:.4f} T={train_losses['temporal']:.4f}) | "
        f"Val: {val_losses['total']:.4f} | "
        f"AUROC: {metrics['auroc']:.4f} AUPRC: {metrics['auprc']:.4f} "
        f"F1: {metrics['f1']:.4f} P: {metrics['precision']:.4f} R: {metrics['recall']:.4f} | "
        f"LR: {lr:.6f}"
    )


def log_results(logger, best_metrics, best_val_loss):
    """Write the [RESULTS] section at the end of training."""
    logger.info("")
    logger.info("[RESULTS]")
    logger.info(f"  Best val_loss: {best_val_loss:.4f}")
    logger.info(f"  Best AUROC:    {best_metrics.get('auroc', 0):.4f}")
    logger.info(f"  Best AUPRC:    {best_metrics.get('auprc', 0):.4f}")
    logger.info(f"  Best F1:       {best_metrics.get('f1', 0):.4f}")
    logger.info(f"  Best Precision:{best_metrics.get('precision', 0):.4f}")
    logger.info(f"  Best Recall:   {best_metrics.get('recall', 0):.4f}")
    logger.info("=" * 60)


def log_test_results(logger, losses, metrics, n_samples, n_anomalous):
    """Write test evaluation section."""
    logger.info("")
    logger.info("[TEST RESULTS]")
    logger.info(f"  Loss:      {losses['total']:.4f} "
                f"(R={losses['recon']:.4f} C={losses['contrastive']:.4f} T={losses['temporal']:.4f})")
    logger.info(f"  AUROC:     {metrics['auroc']:.4f}")
    logger.info(f"  AUPRC:     {metrics['auprc']:.4f}")
    logger.info(f"  F1:        {metrics['f1']:.4f}")
    logger.info(f"  Precision: {metrics['precision']:.4f}")
    logger.info(f"  Recall:    {metrics['recall']:.4f}")
    logger.info(f"  Samples: {n_samples} (anomalous={n_anomalous}, normal={n_samples - n_anomalous})")
    logger.info("=" * 60)


class EpochCSVWriter:
    """Context manager that writes per-epoch metrics to a CSV file."""

    COLUMNS = [
        "epoch", "train_total", "train_recon", "train_contrastive", "train_temporal",
        "val_total", "val_recon", "val_contrastive", "val_temporal",
        "auroc", "auprc", "f1", "precision", "recall", "lr",
    ]

    def __init__(self, log_path):
        """Open CSV next to the .log file, replacing .log with _epochs.csv."""
        csv_path = str(log_path).replace(".log", "_epochs.csv")
        self._file = open(csv_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.COLUMNS)

    def write_row(self, epoch, train_losses, val_losses, metrics, lr):
        self._writer.writerow([
            epoch,
            f"{train_losses['total']:.6f}",
            f"{train_losses['recon']:.6f}",
            f"{train_losses['contrastive']:.6f}",
            f"{train_losses['temporal']:.6f}",
            f"{val_losses['total']:.6f}",
            f"{val_losses['recon']:.6f}",
            f"{val_losses['contrastive']:.6f}",
            f"{val_losses['temporal']:.6f}",
            f"{metrics['auroc']:.6f}",
            f"{metrics['auprc']:.6f}",
            f"{metrics['f1']:.6f}",
            f"{metrics['precision']:.6f}",
            f"{metrics['recall']:.6f}",
            f"{lr:.8f}",
        ])
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
