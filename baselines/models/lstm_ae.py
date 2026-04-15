from __future__ import annotations
import torch
import torch.nn as nn

class LSTMAE(nn.Module):
    """LSTM autoencoder for 8-step sequences of 60-dim per-window features.

    Trains on normal sequences to minimize reconstruction MSE; at eval time,
    per-sample MSE serves as the anomaly score.
    """
    def __init__(self, input_dim: int = 60, hidden_dim: int = 128,
                 latent_dim: int = 64, num_layers: int = 2,
                 seq_len: int = 8, dropout: float = 0.1):
        super().__init__()
        self.seq_len = seq_len
        self.encoder = nn.LSTM(
            input_size=input_dim, hidden_size=hidden_dim,
            num_layers=num_layers, batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.to_latent = nn.Linear(hidden_dim, latent_dim)
        self.decoder = nn.LSTM(
            input_size=latent_dim, hidden_size=hidden_dim,
            num_layers=num_layers, batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.to_output = nn.Linear(hidden_dim, input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (h_n, _) = self.encoder(x)            # h_n: [num_layers, B, hidden]
        z = self.to_latent(h_n[-1])              # [B, latent]
        z_seq = z.unsqueeze(1).expand(-1, self.seq_len, -1)  # [B, T, latent]
        dec, _ = self.decoder(z_seq)             # [B, T, hidden]
        recon = self.to_output(dec)              # [B, T, input_dim]
        return recon
