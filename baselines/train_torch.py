"""Generic training / scoring loops for AE-style anomaly-detection baselines.

`train_ae` runs one-class reconstruction training (normal-only) with early
stopping on validation reconstruction MSE. `score_ae` returns per-sample
reconstruction error (higher = more anomalous) plus the original labels so
the caller can compute ROC/PR against the ground truth.
"""

from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train_ae(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    device: str,
    epochs: int,
    lr: float,
    weight_decay: float = 0.0,
    patience: int = 5,
    verbose: bool = False,
) -> None:
    """One-class reconstruction training with early stopping on val loss."""
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    criterion = nn.MSELoss()

    best_val = float("inf")
    bad_epochs = 0

    for epoch in range(epochs):
        model.train()
        for x, _ in train_loader:
            x = x.to(device)
            recon = model(x)
            loss = criterion(recon, x)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        val_sum, val_n = 0.0, 0
        with torch.no_grad():
            for x, _ in val_loader:
                x = x.to(device)
                recon = model(x)
                val_sum += criterion(recon, x).item() * x.shape[0]
                val_n += x.shape[0]
        val_loss = val_sum / max(val_n, 1)

        if verbose:
            print(f"  [epoch {epoch + 1}/{epochs}] val_mse={val_loss:.5f}")

        if val_loss < best_val:
            best_val = val_loss
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                if verbose:
                    print(f"  early stop at epoch {epoch + 1}")
                break


@torch.no_grad()
def score_ae(model: nn.Module, loader: DataLoader, device: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return per-sample reconstruction MSE and ground-truth labels as numpy arrays.

    Non-finite scores (NaN/Inf) are replaced with 10x the largest finite
    score so the offending samples rank as the most anomalous — this keeps
    sklearn's roc_auc_score happy when a model occasionally blows up on an
    out-of-distribution input rather than aborting the whole baseline run.
    """
    model.to(device).eval()
    scores, labels = [], []
    for x, y in loader:
        x = x.to(device)
        recon = model(x)
        # Per-sample MSE across all feature dims.
        err = ((recon - x) ** 2).reshape(x.shape[0], -1).mean(dim=1)
        scores.append(err.cpu())
        labels.append(y.cpu())
    s = torch.cat(scores).numpy().astype(np.float32)
    y = torch.cat(labels).numpy().astype(np.int64)
    if not np.all(np.isfinite(s)):
        finite = s[np.isfinite(s)]
        replacement = float(finite.max()) * 10.0 if finite.size else 1.0
        s = np.nan_to_num(s, nan=replacement, posinf=replacement, neginf=0.0)
    return s, y
