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
    """Bidirectional cross-attention fusion over full encoder sequences.

    Architecture:
        z1_seq: [B, T1, d_model]   (Stream 1 post-Mamba, full sequence)
        z2_seq: [B, T2, d_model]   (Stream 2 post-Transformer, full sequence)
        CrossAttn1: z1 attends to z2 (MultiheadAttention, with z2 key-padding) + residual + LayerNorm
        CrossAttn2: z2 attends to z1 (MultiheadAttention, with z1 key-padding) + residual + LayerNorm
        Masked mean-pool each fused sequence over time → [B, d_model]
        Concat [z1_fused, z2_fused] → [B, 2*d_model]
        MLP: Linear(2*d_model, 2*d_model) → ReLU → Linear(2*d_model, latent_dim)

    Per-head attention weights from each direction are cached on
    ``self._last_attn_weights`` (detached) so they can be inspected by
    interpretability hooks after any forward pass.
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

        # Cache for most recent per-head attention weights. Populated in forward.
        # Keys: "1to2" [B, heads, T1, T2], "2to1" [B, heads, T2, T1]
        self._last_attn_weights = None

    @staticmethod
    def _masked_mean(seq, mask):
        """Mean-pool ``seq`` [B, T, D] over time using float mask [B, T] (1=real, 0=pad).

        If ``mask`` is None, falls back to plain mean over the time dimension.
        Uses clamp(min=1) on the denominator to protect against all-padding rows.
        """
        if mask is None:
            return seq.mean(dim=1)
        mask_f = mask.to(seq.dtype).unsqueeze(-1)          # [B, T, 1]
        numer = (seq * mask_f).sum(dim=1)                  # [B, D]
        denom = mask_f.sum(dim=1).clamp(min=1.0)           # [B, 1]
        return numer / denom

    @staticmethod
    def _safe_key_padding_mask(mask):
        """Build a bool key_padding_mask (True=ignore) that never marks every
        key as padded for any sample. If a row is all-padding, un-pad position 0
        so softmax has at least one valid key and can't produce NaN.
        """
        if mask is None:
            return None
        kpm = (mask == 0)
        all_padded = kpm.all(dim=1)
        if all_padded.any():
            kpm = kpm.clone()
            kpm[all_padded, 0] = False
        return kpm

    def forward(self, z1_seq, z2_seq, z1_mask=None, z2_mask=None, return_attention=False):
        """
        Args:
            z1_seq: [B, T1, d_model] — Stream 1 full sequence
            z2_seq: [B, T2, d_model] — Stream 2 full sequence
            z1_mask: [B, T1] float/bool (1=real, 0=pad) or None (all real)
            z2_mask: [B, T2] float/bool (1=real, 0=pad) or None (all real)
            return_attention: if True, return (latent, attn_dict) instead of latent.

        Returns:
            latent: [B, latent_dim]
            attn_dict (only when return_attention=True):
                {"1to2": [B, heads, T1, T2], "2to1": [B, heads, T2, T1]}
        """
        # torch.MultiheadAttention key_padding_mask convention: True = ignore.
        # Our dataset mask convention: 1 = real, 0 = padding → invert.
        # Force at least one real key per sample so softmax over all-masked rows
        # never produces NaN (happens for benign windows with no action records).
        kpm_z2 = self._safe_key_padding_mask(z2_mask)
        kpm_z1 = self._safe_key_padding_mask(z1_mask)

        # --- z1 attends to z2 -----------------------------------------------------
        fused_1to2, attn_1to2 = self.cross_attn_1to2(
            query=z1_seq, key=z2_seq, value=z2_seq,
            key_padding_mask=kpm_z2,
            need_weights=True, average_attn_weights=False,
        )  # fused_1to2: [B, T1, d_model]; attn_1to2: [B, heads, T1, T2]
        z1_out = self.norm1(z1_seq + fused_1to2)  # [B, T1, d_model]

        # --- z2 attends to z1 -----------------------------------------------------
        fused_2to1, attn_2to1 = self.cross_attn_2to1(
            query=z2_seq, key=z1_seq, value=z1_seq,
            key_padding_mask=kpm_z1,
            need_weights=True, average_attn_weights=False,
        )  # fused_2to1: [B, T2, d_model]; attn_2to1: [B, heads, T2, T1]
        z2_out = self.norm2(z2_seq + fused_2to1)  # [B, T2, d_model]

        # --- Masked mean-pool each fused sequence over time ------------------------
        z1_pooled = self._masked_mean(z1_out, z1_mask)  # [B, d_model]
        z2_pooled = self._masked_mean(z2_out, z2_mask)  # [B, d_model]

        # --- Concat + MLP ---------------------------------------------------------
        combined = torch.cat([z1_pooled, z2_pooled], dim=-1)  # [B, 2*d_model]
        latent = self.mlp(combined)                            # [B, latent_dim]

        # Cache detached weights for interpretability hooks (always).
        self._last_attn_weights = {
            "1to2": attn_1to2.detach(),
            "2to1": attn_2to1.detach(),
        }

        if return_attention:
            return latent, {"1to2": attn_1to2, "2to1": attn_2to1}
        return latent


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
