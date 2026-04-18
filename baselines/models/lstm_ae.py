"""LSTM sequence autoencoder baseline.

Encoder: single-layer LSTM that consumes the full sequence and returns the
last hidden state as the sequence embedding. Decoder: single-layer LSTM
conditioned on the repeated bottleneck vector, projected back to the
original feature dimension per timestep.
"""

import torch
import torch.nn as nn


class LSTMAE(nn.Module):
    def __init__(self, input_dim: int = 32, hidden_dim: int = 64):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.encoder = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.decoder = nn.LSTM(hidden_dim, hidden_dim, batch_first=True)
        self.out = nn.Linear(hidden_dim, input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T, F]
        B, T, _ = x.shape
        _, (h, _) = self.encoder(x)
        # Repeat last hidden across the time axis as the decoder input.
        rep = h[-1].unsqueeze(1).expand(B, T, self.hidden_dim).contiguous()
        decoded, _ = self.decoder(rep)
        return self.out(decoded)
