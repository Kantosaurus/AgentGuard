"""
AgentGuard — Stream 1 Encoder (Mamba-based)

Encodes temporal sequences of telemetry feature vectors using stacked MambaBlocks.
Input: [B, seq_context, 32] → Output: [B, d_model]
"""

import torch
import torch.nn as nn

from models.mamba import MambaBlock


class Stream1Encoder(nn.Module):
    """Mamba-based encoder for Stream 1 (OS telemetry).

    Architecture:
        Linear(input_dim, d_model) → [MambaBlock + residual + LayerNorm] × n_layers
        → last timestep extraction [:, -1, :]
    """

    def __init__(self, input_dim=32, d_model=128, state_dim=128, n_layers=3):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, d_model)

        self.layers = nn.ModuleList()
        self.norms = nn.ModuleList()
        for _ in range(n_layers):
            self.layers.append(MambaBlock(d_model, state_dim))
            self.norms.append(nn.LayerNorm(d_model))

    def forward(self, x, return_sequence=False):
        """
        Args:
            x: [B, seq_context, input_dim] telemetry sequence
            return_sequence: if True, return full sequence [B, seq_context, d_model]
                instead of only the last timestep.
        Returns:
            [B, d_model] encoding from the last timestep (default), or
            [B, seq_context, d_model] full sequence when return_sequence=True.
        """
        x = self.input_proj(x)  # [B, T, d_model]

        for mamba, norm in zip(self.layers, self.norms):
            residual = x
            x = mamba(x)
            x = norm(x + residual)

        if return_sequence:
            return x  # [B, seq_context, d_model]
        return x[:, -1, :]  # [B, d_model] — last timestep
