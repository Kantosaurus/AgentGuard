"""Per-fold tensor assembly for baseline comparisons.

Loads each agent's preprocessed `.pt` file, flattens per-window stream1
features and builds seq_context-long left-padded sequences for RNN/CNN/
transformer AE baselines. Labels carry over from the `.pt` files.
"""

from pathlib import Path
from typing import Dict, List

import torch


def _gather(processed_dir: str, agent_ids: List[str], seq_context: int) -> Dict[str, torch.Tensor]:
    flats, seqs, labels = [], [], []
    for agent_id in agent_ids:
        pt_path = Path(processed_dir) / f"{agent_id}.pt"
        if not pt_path.exists():
            print(f"[baselines.features] {agent_id}: .pt missing, skipping")
            continue
        data = torch.load(pt_path, map_location="cpu", weights_only=True)
        stream1 = data["stream1"].float()   # [N, F]
        lbl = data["labels"].long()         # [N]
        N, F = stream1.shape

        # Build [N, seq_context, F] via left-padded sliding window.
        seq = torch.zeros(N, seq_context, F, dtype=stream1.dtype)
        for i in range(N):
            start = max(0, i - seq_context + 1)
            window = stream1[start:i + 1]
            pad_len = seq_context - window.shape[0]
            if pad_len > 0:
                pad = torch.zeros(pad_len, F, dtype=stream1.dtype)
                window = torch.cat([pad, window], dim=0)
            seq[i] = window

        flats.append(stream1)
        seqs.append(seq)
        labels.append(lbl)

    if not flats:
        return {
            "flat": torch.empty(0, dtype=torch.float32),
            "seq": torch.empty(0, dtype=torch.float32),
            "labels": torch.empty(0, dtype=torch.long),
        }

    return {
        "flat": torch.cat(flats, dim=0),
        "seq": torch.cat(seqs, dim=0),
        "labels": torch.cat(labels, dim=0),
    }


def build_fold_tensors(processed_dir, train_ids, val_ids, test_ids, seq_context=8):
    """Return {"train": {...}, "val": {...}, "test": {...}}.

    Each split dict contains:
      flat:   [N, F]       — per-window stream1 feature vector
      seq:    [N, T, F]    — left-padded sliding window of length seq_context
      labels: [N]          — binary label tensor (0 = normal, 1 = anomaly)
    """
    return {
        "train": _gather(processed_dir, train_ids, seq_context),
        "val":   _gather(processed_dir, val_ids,   seq_context),
        "test":  _gather(processed_dir, test_ids,  seq_context),
    }
