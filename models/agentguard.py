"""
AgentGuard — Full Composed Model

Combines Stream 1 encoder (Mamba), Stream 2 encoder (Transformer),
cross-attention fusion, reconstruction decoders, and anomaly classification head.
"""

import torch
import torch.nn as nn

from models.stream1_encoder import Stream1Encoder
from models.stream2_encoder import Stream2Encoder
from models.fusion import build_fusion


class AgentGuardModel(nn.Module):
    """Full AgentGuard dual-stream anomaly detection model.

    Architecture:
        Stream 1 encoder (Mamba)      → [B, d_model]
        Stream 2 encoder (Transformer) → [B, d_model]
        Cross-attention fusion          → [B, latent_dim]  (latent)
        Stream 1 decoder               → [B, stream1_dim] (reconstruction)
        Stream 2 decoder               → [B, max_seq_len * stream2_dim] (reconstruction)
        Anomaly head                   → [B, 1] (sigmoid score)
    """

    def __init__(self, stream1_input_dim=32, stream2_input_dim=28,
                 d_model=128, latent_dim=128,
                 mamba_layers=3, mamba_state_dim=128,
                 transformer_layers=3, transformer_heads=4,
                 transformer_ff_dim=512, dropout=0.1, max_seq_len=64,
                 fusion_strategy="cross_attention",
                 cls_head_layers=2, cls_head_hidden_dim=64,
                 cls_head_activation="relu", decoder_activation="relu"):
        super().__init__()

        self.max_seq_len = max_seq_len
        self.stream2_input_dim = stream2_input_dim
        # Cross-attention fusion consumes full encoder sequences;
        # all other strategies consume pooled [B, d_model] vectors.
        self.fusion_strategy = fusion_strategy
        self.use_sequence_fusion = (fusion_strategy == "cross_attention")

        act_fn = self._get_activation(decoder_activation)
        cls_act_fn = self._get_activation(cls_head_activation)

        # Encoders
        self.stream1_encoder = Stream1Encoder(
            input_dim=stream1_input_dim, d_model=d_model,
            state_dim=mamba_state_dim, n_layers=mamba_layers,
        )
        self.stream2_encoder = Stream2Encoder(
            input_dim=stream2_input_dim, d_model=d_model,
            n_heads=transformer_heads, n_layers=transformer_layers,
            dim_feedforward=transformer_ff_dim, dropout=dropout,
            max_len=max_seq_len,
        )

        # Fusion
        self.fusion = build_fusion(
            strategy=fusion_strategy, d_model=d_model,
            n_heads=transformer_heads, latent_dim=latent_dim,
        )

        # Reconstruction decoders
        self.stream1_decoder = nn.Sequential(
            nn.Linear(latent_dim, latent_dim),
            act_fn(),
            nn.Linear(latent_dim, stream1_input_dim),
        )
        self.stream2_decoder = nn.Sequential(
            nn.Linear(latent_dim, 256),
            act_fn(),
            nn.Linear(256, max_seq_len * stream2_input_dim),
        )

        # Anomaly classification head (dynamic depth)
        self.anomaly_head = self._build_cls_head(
            latent_dim, cls_head_layers, cls_head_hidden_dim, cls_act_fn,
        )

    @staticmethod
    def _get_activation(name):
        """Return activation class by string name."""
        activations = {"relu": nn.ReLU, "gelu": nn.GELU, "silu": nn.SiLU}
        if name not in activations:
            raise ValueError(f"Unknown activation: {name}. Choose from {list(activations)}")
        return activations[name]

    @staticmethod
    def _build_cls_head(latent_dim, n_layers, hidden_dim, act_cls):
        """Build anomaly classification head with variable depth."""
        if n_layers == 1:
            return nn.Sequential(nn.Linear(latent_dim, 1), nn.Sigmoid())
        elif n_layers == 2:
            return nn.Sequential(
                nn.Linear(latent_dim, hidden_dim), act_cls(),
                nn.Linear(hidden_dim, 1), nn.Sigmoid(),
            )
        elif n_layers == 3:
            return nn.Sequential(
                nn.Linear(latent_dim, hidden_dim), act_cls(),
                nn.Linear(hidden_dim, hidden_dim // 2), act_cls(),
                nn.Linear(hidden_dim // 2, 1), nn.Sigmoid(),
            )
        else:
            raise ValueError(f"cls_head_layers must be 1, 2, or 3, got {n_layers}")

    def forward(self, stream1, stream2_seq, stream2_mask, return_attention=False):
        """
        Args:
            stream1:      [B, seq_context, stream1_input_dim]
            stream2_seq:  [B, max_seq_len, stream2_input_dim]
            stream2_mask: [B, max_seq_len]
            return_attention: if True AND using cross-attention fusion, the
                returned dict additionally contains an "attention_weights" entry
                with per-head weights {"1to2": [B, H, T1, T2], "2to1": [B, H, T2, T1]}.
        Returns:
            dict with keys: latent, stream1_recon, stream2_recon, anomaly_score
            (plus optionally attention_weights, see above).
        """
        attn_dict = None

        if self.use_sequence_fusion:
            # Encode both streams as full sequences for cross-attention over time
            z1_seq = self.stream1_encoder(stream1, return_sequence=True)   # [B, T1, d_model]
            z2_seq = self.stream2_encoder(stream2_seq, stream2_mask, return_sequence=True)  # [B, T2, d_model]

            # Stream 1 has no padding; Stream 2 uses stream2_mask.
            fusion_out = self.fusion(
                z1_seq, z2_seq,
                z1_mask=None, z2_mask=stream2_mask,
                return_attention=return_attention,
            )
            if return_attention:
                latent, attn_dict = fusion_out
            else:
                latent = fusion_out
        else:
            # Pooled-vector fusion path (concat_mlp, gated, attention_pool).
            z1 = self.stream1_encoder(stream1)                             # [B, d_model]
            z2 = self.stream2_encoder(stream2_seq, stream2_mask)           # [B, d_model]
            latent = self.fusion(z1, z2)                                   # [B, latent_dim]

        # Decode for reconstruction
        stream1_recon = self.stream1_decoder(latent)  # [B, stream1_input_dim]
        stream2_recon_flat = self.stream2_decoder(latent)  # [B, max_seq_len * stream2_dim]
        stream2_recon = stream2_recon_flat.view(-1, self.max_seq_len, self.stream2_input_dim)

        # Anomaly score
        anomaly_score = self.anomaly_head(latent)  # [B, 1]

        outputs = {
            "latent": latent,
            "stream1_recon": stream1_recon,
            "stream2_recon": stream2_recon,
            "anomaly_score": anomaly_score,
        }
        # Only include attention_weights when it's genuinely available:
        # cross-attention fusion AND caller requested it.
        if return_attention and attn_dict is not None:
            outputs["attention_weights"] = attn_dict
        return outputs
