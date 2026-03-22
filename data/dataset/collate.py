"""
AgentGuard — Custom collate function for DataLoader.

Handles batching of dict-based returns from AgentGuardDataset.
"""

import torch
from torch.distributions import Beta


def agentguard_collate(batch):
    """Collate a list of sample dicts into a batched dict of tensors.

    Input: list of dicts, each with keys:
        stream1, stream2_seq, stream2_mask, label, window_idx, agent_idx

    Output: dict with same keys, values stacked into batch tensors.
    """

    if len(batch) == 0:
        return None
    return {
        "stream1": torch.stack([s["stream1"] for s in batch]),        # [B, seq_context, 32]
        "stream2_seq": torch.stack([s["stream2_seq"] for s in batch]), # [B, 64, 28]
        "stream2_mask": torch.stack([s["stream2_mask"] for s in batch]), # [B, 64]
        "label": torch.stack([s["label"] for s in batch]),             # [B]
        "window_idx": torch.tensor([s["window_idx"] for s in batch], dtype=torch.long),  # [B]
        "agent_idx": torch.tensor([s["agent_idx"] for s in batch], dtype=torch.long),    # [B]
    }


class MixupCollate:
    """Wraps agentguard_collate with mixup augmentation.

    After standard collation, interpolates features and labels between
    random pairs using a Beta distribution.
    """

    def __init__(self, alpha=0.2):
        self.alpha = alpha

    def __call__(self, batch):
        collated = agentguard_collate(batch)
        B = collated["stream1"].size(0)
        if B < 2:
            return collated

        lam = Beta(self.alpha, self.alpha).sample((B,))

        # Shuffle indices for pairing
        perm = torch.randperm(B)

        # Expand lambda for broadcasting
        lam_s1 = lam.view(B, 1, 1)  # [B, 1, 1] for stream1
        lam_s2 = lam.view(B, 1, 1)  # [B, 1, 1] for stream2_seq
        lam_label = lam               # [B] for labels

        collated["stream1"] = lam_s1 * collated["stream1"] + (1 - lam_s1) * collated["stream1"][perm]
        collated["stream2_seq"] = lam_s2 * collated["stream2_seq"] + (1 - lam_s2) * collated["stream2_seq"][perm]
        collated["label"] = lam_label * collated["label"].float() + (1 - lam_label) * collated["label"][perm].float()

        return collated
