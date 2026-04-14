"""Adjacent-action-pair gradient scoring.

Scores each adjacent pair ``(i, i+1)`` in the Stream 2 action sequence by the
L2 norm of ``grad(anomaly_score, stream2_seq[i]) + grad(anomaly_score, stream2_seq[i+1])``
where both positions are valid (mask == 1). Also decodes event_type and tool
name for each position from their one-hot slots.
"""

from __future__ import annotations

from typing import List, Dict, Tuple

import torch

from data.preprocessing import EVENT_TYPES, KNOWN_TOOLS, NUM_TOOL_SLOTS


# Inverse lookup tables built once at import.
_INV_EVENT_TYPES: Dict[int, str] = {v: k for k, v in EVENT_TYPES.items()}
_INV_KNOWN_TOOLS: Dict[int, str] = {v: k for k, v in KNOWN_TOOLS.items()}


def _decode_event_type(event_slice: torch.Tensor) -> str:
    """Return the event type name from the 5-dim one-hot slice, or ''."""
    if event_slice.sum().item() <= 0:
        return ""
    idx = int(torch.argmax(event_slice).item())
    return _INV_EVENT_TYPES.get(idx, "")


def _decode_tool(tool_slice: torch.Tensor) -> str:
    """Return the tool name from the 16-dim one-hot slice, or ''.

    Unknown tools (hash slots >= len(KNOWN_TOOLS)) are reported as
    ``"unknown_tool_{slot}"`` so the report still distinguishes them.
    """
    if tool_slice.sum().item() <= 0:
        return ""
    idx = int(torch.argmax(tool_slice).item())
    if idx in _INV_KNOWN_TOOLS:
        return _INV_KNOWN_TOOLS[idx]
    # hashed slot -- preserve identity for the report
    if 0 <= idx < NUM_TOOL_SLOTS:
        return f"unknown_tool_{idx}"
    return ""


def flag_action_pairs(model, stream1, stream2_seq, stream2_mask,
                      top_k: int = 5) -> List[Dict]:
    """Score adjacent action pairs by gradient L2 norm of the anomaly score.

    Args:
        model: AgentGuardModel.
        stream1:     [1, seq_context, 32] tensor.
        stream2_seq: [1, max_seq_len, 28] tensor.
        stream2_mask:[1, max_seq_len] tensor.
        top_k: number of top-scoring pairs to return.

    Returns:
        list of dicts sorted by magnitude desc, each with keys:
            position (int), magnitude (float),
            event_types (tuple[str, str]), tools (tuple[str, str]).
    """
    was_training = model.training
    model.eval()

    stream1 = stream1.detach().clone().float()
    stream2_seq = stream2_seq.detach().clone().float().requires_grad_(True)
    stream2_mask = stream2_mask.detach()

    out = model(stream1, stream2_seq, stream2_mask)
    score = out["anomaly_score"]  # [1, 1]
    score = score.sum()  # scalar, grads flow identically for B=1

    model.zero_grad(set_to_none=True)
    grad = torch.autograd.grad(score, stream2_seq, retain_graph=False)[0]
    # grad: [1, max_seq_len, 28]
    grad_vec = grad.squeeze(0).detach().cpu()           # [max_seq_len, 28]
    per_pos_norm = grad_vec.norm(p=2, dim=-1)           # [max_seq_len]

    seq = stream2_seq.squeeze(0).detach().cpu()         # [max_seq_len, 28]
    mask = stream2_mask.squeeze(0).detach().cpu()       # [max_seq_len]
    max_len = seq.shape[0]

    scored: List[Dict] = []
    for i in range(max_len - 1):
        if mask[i].item() < 0.5 or mask[i + 1].item() < 0.5:
            continue
        magnitude = float(per_pos_norm[i].item() + per_pos_norm[i + 1].item())

        e1 = _decode_event_type(seq[i, 0:5])
        e2 = _decode_event_type(seq[i + 1, 0:5])
        t1 = _decode_tool(seq[i, 5:21])
        t2 = _decode_tool(seq[i + 1, 5:21])

        scored.append({
            "position": int(i),
            "magnitude": magnitude,
            "event_types": (e1, e2),
            "tools": (t1, t2),
        })

    scored.sort(key=lambda d: d["magnitude"], reverse=True)

    if was_training:
        model.train()

    return scored[:top_k]
