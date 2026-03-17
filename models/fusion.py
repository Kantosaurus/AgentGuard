"""
AgentGuard — Fusion Modules

Merges Stream 1 and Stream 2 latent representations into a unified latent space.
Input: z1 [B, d_model], z2 [B, d_model] → Output: [B, latent_dim]

Strategies:
  - CrossAttentionFusion: Bidirectional cross-attention + MLP projection
  - ConcatMLPFusion: Concatenate → MLP
  - GatedFusion: Learnable sigmoid gate → linear projection
  - AttentionPoolFusion: Stack as 2-token sequence → self-attention → mean pool
"""

import torch
import torch.nn as nn


class CrossAttentionFusion(nn.Module):
    """Bidirectional cross-attention fusion for dual-stream embeddings.

    Architecture:
        z1, z2 unsqueeze to [B, 1, d_model]
        CrossAttn1: z1 attends to z2 (MultiheadAttention) + residual + LayerNorm
        CrossAttn2: z2 attends to z1 (MultiheadAttention) + residual + LayerNorm
        Concat [z1_fused, z2_fused] → [B, 2*d_model]
        MLP: Linear(2*d_model, 2*d_model) → ReLU → Linear(2*d_model, latent_dim)
    """

    def __init__(self, d_model=128, n_heads=4, latent_dim=128):
        super().__init__()

        # Cross-attention: z1 attends to z2
        self.cross_attn_1to2 = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=n_heads, batch_first=True
        )
        self.norm1 = nn.LayerNorm(d_model)

        # Cross-attention: z2 attends to z1
        self.cross_attn_2to1 = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=n_heads, batch_first=True
        )
        self.norm2 = nn.LayerNorm(d_model)

        # Projection MLP
        self.mlp = nn.Sequential(
            nn.Linear(2 * d_model, 2 * d_model),
            nn.ReLU(),
            nn.Linear(2 * d_model, latent_dim),
        )

    def forward(self, z1, z2):
        """
        Args:
            z1: [B, d_model] — Stream 1 encoding
            z2: [B, d_model] — Stream 2 encoding
        Returns:
            [B, latent_dim] — fused latent representation
        """
        # Unsqueeze to sequence length 1 for attention
        z1_seq = z1.unsqueeze(1)  # [B, 1, d_model]
        z2_seq = z2.unsqueeze(1)  # [B, 1, d_model]

        # z1 attends to z2 + residual + norm
        z1_attn, _ = self.cross_attn_1to2(query=z1_seq, key=z2_seq, value=z2_seq)
        z1_fused = self.norm1(z1_seq + z1_attn).squeeze(1)  # [B, d_model]

        # z2 attends to z1 + residual + norm
        z2_attn, _ = self.cross_attn_2to1(query=z2_seq, key=z1_seq, value=z1_seq)
        z2_fused = self.norm2(z2_seq + z2_attn).squeeze(1)  # [B, d_model]

        # Concat + MLP
        combined = torch.cat([z1_fused, z2_fused], dim=-1)  # [B, 2*d_model]
        return self.mlp(combined)  # [B, latent_dim]


class ConcatMLPFusion(nn.Module):
    """Concatenate z1, z2 then project through MLP. Simplest baseline."""

    def __init__(self, d_model=128, latent_dim=128):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(2 * d_model, 2 * d_model),
            nn.ReLU(),
            nn.Linear(2 * d_model, latent_dim),
        )

    def forward(self, z1, z2):
        return self.mlp(torch.cat([z1, z2], dim=-1))


class GatedFusion(nn.Module):
    """Learnable sigmoid gate: g = sigmoid(W·[z1;z2]), out = g*z1 + (1-g)*z2."""

    def __init__(self, d_model=128, latent_dim=128):
        super().__init__()
        self.gate = nn.Linear(2 * d_model, d_model)
        self.proj = nn.Linear(d_model, latent_dim)

    def forward(self, z1, z2):
        g = torch.sigmoid(self.gate(torch.cat([z1, z2], dim=-1)))
        fused = g * z1 + (1 - g) * z2
        return self.proj(fused)


class AttentionPoolFusion(nn.Module):
    """Stack z1, z2 as 2-token sequence → self-attention → mean pool → linear."""

    def __init__(self, d_model=128, n_heads=4, latent_dim=128):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(
            embed_dim=d_model, num_heads=n_heads, batch_first=True
        )
        self.norm = nn.LayerNorm(d_model)
        self.proj = nn.Linear(d_model, latent_dim)

    def forward(self, z1, z2):
        seq = torch.stack([z1, z2], dim=1)  # [B, 2, d_model]
        attn_out, _ = self.self_attn(seq, seq, seq)
        seq = self.norm(seq + attn_out)
        pooled = seq.mean(dim=1)  # [B, d_model]
        return self.proj(pooled)


def build_fusion(strategy, d_model, n_heads, latent_dim):
    """Factory: return the fusion module for a given strategy name."""
    if strategy == "cross_attention":
        return CrossAttentionFusion(d_model=d_model, n_heads=n_heads, latent_dim=latent_dim)
    elif strategy == "concat_mlp":
        return ConcatMLPFusion(d_model=d_model, latent_dim=latent_dim)
    elif strategy == "gated":
        return GatedFusion(d_model=d_model, latent_dim=latent_dim)
    elif strategy == "attention_pool":
        return AttentionPoolFusion(d_model=d_model, n_heads=n_heads, latent_dim=latent_dim)
    else:
        raise ValueError(f"Unknown fusion strategy: {strategy}")
