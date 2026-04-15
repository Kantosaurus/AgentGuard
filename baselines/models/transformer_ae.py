from __future__ import annotations
import torch
import torch.nn as nn


class TransformerAE(nn.Module):
    """Vanilla Transformer autoencoder on [B, 8, 60] per-window features.

    Tests whether a plain transformer matches AgentGuard's dual-stream design
    when fed the same concatenated 32+28-dim representation.
    """

    def __init__(self, input_dim: int = 60, d_model: int = 128,
                 latent_dim: int = 64, nhead: int = 4, num_layers: int = 2,
                 dim_feedforward: int = 256, seq_len: int = 8,
                 dropout: float = 0.1):
        super().__init__()
        self.seq_len = seq_len
        self.in_proj = nn.Linear(input_dim, d_model)
        self.enc_pos = nn.Parameter(torch.zeros(1, seq_len, d_model))
        self.dec_pos = nn.Parameter(torch.zeros(1, seq_len, d_model))
        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_feedforward,
            dropout=dropout, batch_first=True, activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(enc_layer, num_layers=num_layers)
        self.to_latent = nn.Linear(d_model, latent_dim)
        self.from_latent = nn.Linear(latent_dim, d_model)
        dec_layer = nn.TransformerDecoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_feedforward,
            dropout=dropout, batch_first=True, activation="gelu",
        )
        self.decoder = nn.TransformerDecoder(dec_layer, num_layers=num_layers)
        self.out_proj = nn.Linear(d_model, input_dim)
        nn.init.trunc_normal_(self.enc_pos, std=0.02)
        nn.init.trunc_normal_(self.dec_pos, std=0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.in_proj(x) + self.enc_pos          # [B, T, d]
        mem = self.encoder(h)                        # [B, T, d]
        z = self.to_latent(mem.mean(dim=1))          # [B, latent]
        tgt_base = self.from_latent(z).unsqueeze(1).expand(-1, self.seq_len, -1)
        tgt = tgt_base + self.dec_pos                # [B, T, d]
        dec = self.decoder(tgt, mem)                 # [B, T, d]
        return self.out_proj(dec)                    # [B, T, input_dim]
