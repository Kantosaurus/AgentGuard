"""1-D convolutional sequence autoencoder baseline.

Convolves along the time axis. Input is [B, T, F]; internally transposed
to [B, F, T] for Conv1d, then transposed back for the MSE loss against
the original feature-last representation.
"""

import torch
import torch.nn as nn


class CNNAE(nn.Module):
    def __init__(self, input_dim: int = 32, hidden_dim: int = 64):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(input_dim, hidden_dim, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv1d(hidden_dim, hidden_dim, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
        )
        self.decoder = nn.Sequential(
            nn.Conv1d(hidden_dim, hidden_dim, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv1d(hidden_dim, input_dim, kernel_size=3, padding=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # [B, T, F] -> [B, F, T] for Conv1d, then back.
        h = x.transpose(1, 2)
        h = self.encoder(h)
        h = self.decoder(h)
        return h.transpose(1, 2)
