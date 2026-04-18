"""Deep SVDD baseline (Ruff et al., 2018).

Learns a neural embedding that maps normal samples close to a fixed
hypersphere center `c` in feature space; anomaly score is the squared
distance from the embedding to `c`. Per the paper: no biases anywhere in
the network, and `c` is initialized as the mean of training-sample
embeddings after a forward pass, with |c_i| < 0.1 nudged to ±0.1 to
avoid a trivial all-zero solution.
"""

from typing import Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


class DeepSVDDNet(nn.Module):
    def __init__(self, input_dim: int = 32, hidden_dim: int = 64, latent_dim: int = 32):
        super().__init__()
        # No biases anywhere in the network (Ruff et al. 2018, §3.1).
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, hidden_dim, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, latent_dim, bias=False),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@torch.no_grad()
def _init_center(model: nn.Module, loader: DataLoader, device: str, eps: float = 0.1) -> torch.Tensor:
    model.eval()
    n, running = 0, None
    for x, _ in loader:
        x = x.to(device)
        z = model(x)
        running = z.sum(dim=0) if running is None else (running + z.sum(dim=0))
        n += z.shape[0]
    c = running / max(n, 1)
    # Avoid a degenerate center that lets the network collapse to zero.
    c[(c.abs() < eps) & (c < 0)] = -eps
    c[(c.abs() < eps) & (c >= 0)] = eps
    return c


def train_deep_svdd(
    model: DeepSVDDNet,
    train_loader: DataLoader,
    val_loader: DataLoader,
    device: str,
    epochs: int,
    lr: float,
    weight_decay: float = 1e-6,
    patience: int = 5,
    verbose: bool = False,
) -> Tuple[DeepSVDDNet, torch.Tensor]:
    """Train a DeepSVDD network; return (model, center)."""
    model.to(device)
    c = _init_center(model, train_loader, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    best_val = float("inf")
    bad_epochs = 0

    for epoch in range(epochs):
        model.train()
        for x, _ in train_loader:
            x = x.to(device)
            z = model(x)
            loss = ((z - c) ** 2).sum(dim=1).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        model.eval()
        val_sum, val_n = 0.0, 0
        with torch.no_grad():
            for x, _ in val_loader:
                x = x.to(device)
                z = model(x)
                val_sum += ((z - c) ** 2).sum(dim=1).sum().item()
                val_n += z.shape[0]
        val_loss = val_sum / max(val_n, 1)

        if verbose:
            print(f"  [epoch {epoch + 1}/{epochs}] val_dist2={val_loss:.5f}")

        if val_loss < best_val:
            best_val = val_loss
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                if verbose:
                    print(f"  early stop at epoch {epoch + 1}")
                break

    return model, c


@torch.no_grad()
def score_deep_svdd(
    model: DeepSVDDNet,
    c: torch.Tensor,
    loader: DataLoader,
    device: str,
) -> Tuple[np.ndarray, np.ndarray]:
    model.to(device).eval()
    c = c.to(device)
    scores, labels = [], []
    for x, y in loader:
        x = x.to(device)
        z = model(x)
        err = ((z - c) ** 2).sum(dim=1)
        scores.append(err.cpu())
        labels.append(y.cpu())
    s = torch.cat(scores).numpy().astype(np.float32)
    y = torch.cat(labels).numpy().astype(np.int64)
    # Same NaN-safe treatment as score_ae — replace non-finite with a large
    # finite value so sklearn's ROC/PR helpers never see NaN.
    if not np.all(np.isfinite(s)):
        finite = s[np.isfinite(s)]
        replacement = float(finite.max()) * 10.0 if finite.size else 1.0
        s = np.nan_to_num(s, nan=replacement, posinf=replacement, neginf=0.0)
    return s, y
