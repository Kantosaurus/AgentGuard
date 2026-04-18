"""
AgentGuard — Stream 2 Encoder (Transformer-based)

Encodes action event sequences using a standard Transformer encoder with
sinusoidal positional encoding and masked mean pooling.
Input: [B, 64, 28] + mask [B, 64] → Output: [B, d_model]
"""

import math
import torch
import torch.nn as nn


class SinusoidalPositionalEncoding(nn.Module):
    """Standard sinusoidal positional encoding."""

    def __init__(self, d_model, max_len=64):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))  # [1, max_len, d_model]

    def forward(self, x):
        """x: [B, T, d_model]"""
        return x + self.pe[:, :x.size(1), :]


class Stream2Encoder(nn.Module):
    """Transformer-based encoder for Stream 2 (LLM action sequences).

    Architecture:
        Linear(input_dim, d_model) → SinusoidalPositionalEncoding
        → TransformerEncoderLayer × n_layers → masked mean pooling
    """

    def __init__(self, input_dim=28, d_model=128, n_heads=4, n_layers=3,
                 dim_feedforward=512, dropout=0.1, max_len=64):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, d_model)
        self.pos_enc = SinusoidalPositionalEncoding(d_model, max_len=max_len)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_heads,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)

    def forward(self, x, mask, return_sequence=False):
        """
        Args:
            x:    [B, max_len, input_dim] action sequence
            mask: [B, max_len] attention mask (1 = real, 0 = padding)
            return_sequence: if True, return post-transformer sequence
                [B, max_len, d_model] instead of masked-mean-pooled [B, d_model].
        Returns:
            [B, d_model] pooled encoding (default), or
            [B, max_len, d_model] full sequence when return_sequence=True.
        """
        x = self.input_proj(x)       # [B, T, d_model]
        x = self.pos_enc(x)

        # TransformerEncoder expects src_key_padding_mask where True = ignore
        padding_mask = (mask == 0)    # [B, T], True where padding

        # if 0 in x.shape:
        #     print(x.shape)
        #     print(x)
        #     # figure out batch size
        #     batch_dim = 0 if self.transformer.batch_first else 1
        #     batch_size = x.size(batch_dim)
        #     x = torch.zeros(batch_size, self.d_model, device=x.device)
        # else:
        try:
            x = self.transformer(x, src_key_padding_mask=padding_mask)  # [B, T, d_model]
        except RuntimeError as e:
            print("X Shape: ", x.shape)
            print("Mask: ", mask)
            print(x)

        if return_sequence:
            return x  # [B, max_len, d_model]

        # Masked mean pooling: average over real tokens only
        mask_expanded = mask.unsqueeze(-1)  # [B, T, 1]
        x = (x * mask_expanded).sum(dim=1)  # [B, d_model]
        counts = mask_expanded.sum(dim=1).clamp(min=1)  # [B, 1]
        x = x / counts

        return x  # [B, d_model]
