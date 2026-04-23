"""Scorer wraps the AgentGuard model for single-sample real-time scoring.

Loads the architecture from ``config.yml``, the weights from the trained
checkpoint, and exposes ``score(stream1, stream2, mask) -> float`` that
returns the anomaly probability for the current window.

Important notes drawn from Phase 1 verification:
  * ``torch.load(..., weights_only=False)`` is required for PyTorch 2.6+.
  * The checkpoint's top-level dict wraps the state dict under
    ``model_state_dict`` — we unwrap it.
  * ``load_state_dict(..., strict=True)`` succeeds because the checkpoint was
    produced by this exact model class.
  * Normalization is applied to Stream 1 only; the model was trained without
    Stream-2 normalization.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np
import torch
import yaml

# Make the repo root importable for ``models.agentguard`` when running inside
# the docker image (PYTHONPATH is already /workspace there, but this lets the
# module import standalone too if the env var is unset).
_WORKSPACE = os.environ.get("AGENTGUARD_WORKSPACE", "/workspace")
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)

from models.agentguard import AgentGuardModel  # noqa: E402

from .config import Config  # noqa: E402


class Scorer:
    """Loads the AgentGuard checkpoint and returns anomaly scores."""

    def __init__(
        self,
        cfg: Config,
        mean: np.ndarray,
        std: np.ndarray,
        *,
        strict_load: bool = True,
    ):
        self.cfg = cfg
        self._mean = torch.from_numpy(mean.astype(np.float32))
        self._std = torch.from_numpy(std.astype(np.float32))

        with open(cfg.config_yaml) as f:
            yml = yaml.safe_load(f)
        m = yml["model"]
        data = yml["data"]

        self.model = AgentGuardModel(
            stream1_input_dim=m["stream1_input_dim"],
            stream2_input_dim=m["stream2_input_dim"],
            d_model=m["d_model"],
            latent_dim=m["latent_dim"],
            mamba_layers=m["mamba_layers"],
            transformer_layers=m["transformer_layers"],
            transformer_heads=m["transformer_heads"],
            transformer_ff_dim=m["transformer_ff_dim"],
            dropout=m["dropout"],
            max_seq_len=data["max_seq_len"],
            fusion_strategy=m["fusion_strategy"],
            cls_head_layers=m["cls_head_layers"],
            cls_head_hidden_dim=m["cls_head_hidden_dim"],
            cls_head_activation=m["cls_head_activation"],
            decoder_activation=m["decoder_activation"],
        )

        state = torch.load(
            cfg.checkpoint_path, map_location="cpu", weights_only=False
        )
        if isinstance(state, dict) and "model_state_dict" in state:
            state = state["model_state_dict"]
        missing, unexpected = self.model.load_state_dict(state, strict=False)
        if strict_load and (missing or unexpected):
            raise RuntimeError(
                f"checkpoint key mismatch under strict=True: "
                f"missing={missing} unexpected={unexpected}"
            )
        self.model.eval()

    def score(
        self,
        stream1: np.ndarray,
        stream2: np.ndarray,
        mask: np.ndarray,
    ) -> float:
        """Run a single forward pass and return the scalar anomaly score.

        Args:
            stream1: (seq_context, 32) float32 — normalized here with mean/std.
            stream2: (max_seq_len, 28) float32 — passed through unchanged.
            mask:    (max_seq_len,) bool — True for valid events.
        """
        if stream1.ndim != 2:
            raise ValueError(f"stream1 must be 2D, got {stream1.shape}")
        if stream2.ndim != 2:
            raise ValueError(f"stream2 must be 2D, got {stream2.shape}")
        if mask.ndim != 1:
            raise ValueError(f"mask must be 1D, got {mask.shape}")

        with torch.no_grad():
            t1 = torch.from_numpy(stream1.astype(np.float32)).unsqueeze(0)
            t1 = (t1 - self._mean) / self._std
            t2 = torch.from_numpy(stream2.astype(np.float32)).unsqueeze(0)
            m = torch.from_numpy(mask.astype(bool)).unsqueeze(0)
            out = self.model(t1, t2, m)
            score_tensor = out["anomaly_score"]
            # anomaly_head returns a [B, 1] sigmoid; squeeze to a scalar.
            return float(score_tensor.view(-1)[0].item())
