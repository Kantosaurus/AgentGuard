from __future__ import annotations
import torch
import torch.nn as nn


class CNNAE(nn.Module):
    """1D-CNN autoencoder for 8-step sequences of 60-dim per-window features.

    Captures local temporal patterns with stacked Conv1d layers; no recurrent
    state. Per-sample reconstruction MSE serves as the anomaly score at eval.
    """

    def __init__(self, input_dim: int = 60, hidden_dim: int = 128,
                 latent_dim: int = 64, seq_len: int = 8):
        super().__init__()
        self.seq_len = seq_len
        self.enc_conv = nn.Sequential(
            nn.Conv1d(input_dim, hidden_dim, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(hidden_dim, latent_dim, kernel_size=3, padding=1),
            nn.ReLU(),
        )
        self.enc_proj = nn.Linear(latent_dim, latent_dim)
        self.dec_proj = nn.Linear(latent_dim, latent_dim)
        self.dec_conv = nn.Sequential(
            nn.Conv1d(latent_dim, hidden_dim, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(hidden_dim, input_dim, kernel_size=3, padding=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, T, input_dim]
        h = self.enc_conv(x.transpose(1, 2))   # [B, latent, T]
        z = self.enc_proj(h.mean(dim=-1))      # [B, latent]
        z_expand = self.dec_proj(z).unsqueeze(-1).expand(-1, -1, self.seq_len)  # [B, latent, T]
        recon = self.dec_conv(z_expand)        # [B, input_dim, T]
        return recon.transpose(1, 2)           # [B, T, input_dim]
