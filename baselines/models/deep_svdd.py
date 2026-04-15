from __future__ import annotations
"""Deep SVDD baseline: bias-free MLP encoder with hypersphere distance scoring."""
import copy
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader


class DeepSVDDNet(nn.Module):
    """MLP encoder for Deep SVDD, bias-free to avoid trivial hypersphere collapse."""

    def __init__(self, input_dim: int = 480, hidden_dims: tuple[int, ...] = (256, 128),
                 latent_dim: int = 64):
        super().__init__()
        dims = [input_dim, *hidden_dims, latent_dim]
        layers = []
        for i in range(len(dims) - 1):
            layers.append(nn.Linear(dims[i], dims[i + 1], bias=False))
            if i < len(dims) - 2:
                layers.append(nn.ReLU())
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


@torch.no_grad()
def _init_center(net: nn.Module, loader: DataLoader, device: str, eps: float = 0.1) -> torch.Tensor:
    net.eval()
    total = None
    count = 0
    for batch in loader:
        x, _ = batch
        if not torch.is_floating_point(x):
            x = x.float()
        x = x.to(device)
        z = net(x)
        if total is None:
            total = z.sum(dim=0)
        else:
            total = total + z.sum(dim=0)
        count += z.shape[0]
    if count == 0:
        raise ValueError("loader is empty; cannot initialize center")
    c = total / count
    small = c.abs() < eps
    sign = torch.where(c >= 0, torch.ones_like(c), -torch.ones_like(c))
    c = torch.where(small, sign * eps, c)
    return c


def train_deep_svdd(net: nn.Module, train_loader: DataLoader, val_loader: DataLoader,
                    device: str = "cpu", epochs: int = 50, lr: float = 1e-3,
                    weight_decay: float = 1e-6, patience: int = 5,
                    verbose: bool = False) -> tuple[nn.Module, torch.Tensor]:
    if len(train_loader) == 0:
        raise ValueError("train_loader is empty; cannot train")
    if len(val_loader) == 0:
        raise ValueError("val_loader is empty; cannot validate")

    net.to(device)
    c = _init_center(net, train_loader, device)
    c = c.to(device)

    optim = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
    best_val = float("inf")
    best_state = copy.deepcopy(net.state_dict())
    bad = 0

    for epoch in range(1, epochs + 1):
        net.train()
        train_sum = 0.0
        train_n = 0
        for x, _ in train_loader:
            if not torch.is_floating_point(x):
                x = x.float()
            x = x.to(device)
            z = net(x)
            loss = ((z - c) ** 2).sum(dim=1).mean()
            optim.zero_grad()
            loss.backward()
            optim.step()
            train_sum += loss.item() * x.shape[0]
            train_n += x.shape[0]
        train_loss = train_sum / train_n

        net.eval()
        val_sum = 0.0
        val_n = 0
        with torch.no_grad():
            for x, _ in val_loader:
                if not torch.is_floating_point(x):
                    x = x.float()
                x = x.to(device)
                z = net(x)
                d = ((z - c) ** 2).sum(dim=1)
                val_sum += d.sum().item()
                val_n += x.shape[0]
        val_loss = val_sum / val_n

        if val_loss < best_val:
            best_val = val_loss
            best_state = copy.deepcopy(net.state_dict())
            bad = 0
        else:
            bad += 1

        if verbose:
            print(f"[SVDD] epoch {epoch:03d}/{epochs:03d} train={train_loss:.4f} val={val_loss:.4f} best={best_val:.4f}")

        if bad >= patience:
            break

    net.load_state_dict(best_state)
    net.eval()
    return net, c


@torch.no_grad()
def score_deep_svdd(net: nn.Module, c: torch.Tensor, loader: DataLoader,
                    device: str = "cpu") -> tuple[np.ndarray, np.ndarray]:
    if len(loader) == 0:
        raise ValueError("loader is empty; cannot score")
    net.eval()
    c = c.to(device)
    scores = []
    labels = []
    for x, y in loader:
        if not torch.is_floating_point(x):
            x = x.float()
        x = x.to(device)
        z = net(x)
        d = ((z - c) ** 2).sum(dim=1)
        scores.append(d.cpu())
        labels.append(y.cpu())
    return torch.cat(scores).numpy(), torch.cat(labels).numpy()
