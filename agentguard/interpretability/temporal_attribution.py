"""Integrated-gradients attribution for AgentGuard.

Computes per-feature attributions of the sigmoid anomaly score to
(Stream 1) telemetry context steps and (Stream 2) action positions
using ``captum.attr.IntegratedGradients``.
"""

from __future__ import annotations

import torch
from captum.attr import IntegratedGradients


def attribute_temporal(model, stream1, stream2_seq, stream2_mask,
                       target: str = "anomaly_score", n_steps: int = 50):
    """Compute Integrated Gradients attribution of the anomaly score.

    Args:
        model: AgentGuardModel, will be placed in eval mode locally.
        stream1:     [1, seq_context, 32] single sample tensor.
        stream2_seq: [1, max_seq_len, 28] single sample tensor.
        stream2_mask:[1, max_seq_len] single sample tensor.
        target: only ``"anomaly_score"`` is supported.
        n_steps: number of IG integration steps.

    Returns:
        dict with keys:
            stream1_attr: Tensor [seq_context, 32]
            stream2_attr: Tensor [max_seq_len, 28]
    """
    if target != "anomaly_score":
        raise ValueError(
            f"attribute_temporal only supports target='anomaly_score', "
            f"got target={target!r}"
        )

    was_training = model.training
    model.eval()

    # Attribute to continuous tensors only; the discrete mask flows through as
    # an additional forward arg.
    stream1 = stream1.detach().clone().float().requires_grad_(True)
    stream2_seq = stream2_seq.detach().clone().float().requires_grad_(True)
    stream2_mask = stream2_mask.detach()

    def model_fn(stream1_inp, stream2_seq_inp, stream2_mask_inp):
        out = model(stream1_inp, stream2_seq_inp, stream2_mask_inp)
        # anomaly_score is [B, 1]; squeeze the scalar dim for captum target=0.
        return out["anomaly_score"]

    ig = IntegratedGradients(model_fn)

    baselines = (
        torch.zeros_like(stream1),
        torch.zeros_like(stream2_seq),
    )

    attributions = ig.attribute(
        inputs=(stream1, stream2_seq),
        baselines=baselines,
        additional_forward_args=(stream2_mask,),
        target=0,
        n_steps=n_steps,
        internal_batch_size=1,
    )

    stream1_attr, stream2_attr = attributions
    # Strip the batch dim: inputs were [1, ...].
    stream1_attr = stream1_attr.detach().squeeze(0).cpu()
    stream2_attr = stream2_attr.detach().squeeze(0).cpu()

    if was_training:
        model.train()

    return {
        "stream1_attr": stream1_attr,
        "stream2_attr": stream2_attr,
    }
