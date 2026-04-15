from __future__ import annotations

import copy

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train_ae(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    device: str = "cpu",
    epochs: int = 50,
    lr: float = 1e-3,
    weight_decay: float = 1e-5,
    patience: int = 5,
    verbose: bool = False,
) -> nn.Module:
    """Train a sequence autoencoder on reconstruction MSE.

    Each batch from train_loader/val_loader yields (x, y) where x is the input
    tensor (shape [B, ...]) and y is the label. Labels are ignored here; the
    caller is responsible for having pre-filtered to label==0 samples only.

    Optimizer: Adam(lr=lr, weight_decay=weight_decay).
    Loss: nn.MSELoss() over model(x) vs x.
    Early stopping: stop if val loss does not improve for `patience` consecutive epochs.
    Keeps and restores the best-state-dict based on val loss.
    Returns the trained model (in eval mode on `device`).
    """
    if len(train_loader) == 0:
        raise ValueError("train_loader is empty; cannot train")
    if len(val_loader) == 0:
        raise ValueError("val_loader is empty; cannot validate")

    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    epochs_no_improve = 0

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss_sum = 0.0
        train_count = 0
        for batch in train_loader:
            x, _ = batch
            if x.dtype != torch.float32:
                x = x.float()
            x = x.to(device)
            optimizer.zero_grad()
            recon = model(x)
            loss = criterion(recon, x)
            loss.backward()
            optimizer.step()
            train_loss_sum += loss.item() * x.shape[0]
            train_count += x.shape[0]
        train_loss = train_loss_sum / train_count if train_count > 0 else 0.0

        model.eval()
        val_loss_sum = 0.0
        val_count = 0
        with torch.no_grad():
            for batch in val_loader:
                x, _ = batch
                if x.dtype != torch.float32:
                    x = x.float()
                x = x.to(device)
                recon = model(x)
                loss = criterion(recon, x)
                val_loss_sum += loss.item() * x.shape[0]
                val_count += x.shape[0]
        val_loss = val_loss_sum / val_count if val_count > 0 else 0.0

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = copy.deepcopy(model.state_dict())
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1

        if verbose:
            print(
                f"[AE] epoch {epoch:03d}/{epochs:03d} "
                f"train={train_loss:.4f} val={val_loss:.4f} best={best_val_loss:.4f}"
            )

        if epochs_no_improve >= patience:
            if verbose:
                print(f"[AE] early stopping at epoch {epoch}")
            break

    model.load_state_dict(best_state)
    model.eval()
    return model


def score_ae(
    model: nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> tuple[np.ndarray, np.ndarray]:
    """Return (scores, labels) where scores[i] is the per-sample MSE of model(x_i)
    against x_i, summed over all non-batch dimensions. scores shape: [N]. labels shape: [N].
    Model is set to eval and torch.no_grad is used throughout. Returns numpy arrays.
    """
    if len(loader) == 0:
        raise ValueError("loader is empty")

    model.eval()

    all_scores = []
    all_labels = []

    with torch.no_grad():
        for batch in loader:
            x, y = batch
            if x.dtype != torch.float32:
                x = x.float()
            x = x.to(device)
            recon = model(x)
            B = x.shape[0]
            per_sample_mse = ((recon - x) ** 2).reshape(B, -1).mean(dim=1)
            all_scores.append(per_sample_mse.cpu().numpy())
            all_labels.append(y.cpu().numpy())

    scores = np.concatenate(all_scores, axis=0)
    labels = np.concatenate(all_labels, axis=0)
    return scores, labels
