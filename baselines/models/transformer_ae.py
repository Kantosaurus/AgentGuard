"""Transformer-encoder sequence autoencoder baseline.

Project input features to d_model, run stacked TransformerEncoder layers
as both encoder and decoder (shallow symmetric design for a baseline),
then project back to input_dim. Uses PyTorch's built-in
TransformerEncoderLayer with batch_first=True so inputs stay [B, T, F]
throughout.
"""

import torch
import torch.nn as nn


class TransformerAE(nn.Module):
    def __init__(
        self,
        input_dim: int = 32,
        d_model: int = 64,
        n_heads: int = 4,
        n_layers: int = 2,
        dim_feedforward: int = 128,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.in_proj = nn.Linear(input_dim, d_model)
        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=dim_feedforward,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=n_layers)
        dec_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=dim_feedforward,
            dropout=dropout, batch_first=True,
        )
        self.decoder = nn.TransformerEncoder(dec_layer, num_layers=n_layers)
        self.out_proj = nn.Linear(d_model, input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.in_proj(x)
        z = self.encoder(z)
        z = self.decoder(z)
        return self.out_proj(z)
