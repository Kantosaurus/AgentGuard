"""
AgentGuard — Unified Dataset

Single dataset returning aligned (stream1, stream2_seq, stream2_mask, label) tuples
from preprocessed .pt files. Groups consecutive windows for Stream 1 temporal context.
"""

import random

import torch
from torch.utils.data import Dataset
from pathlib import Path


class AgentGuardDataset(Dataset):
    """Unified dual-stream dataset for AgentGuard.

    Loads preprocessed .pt files and returns aligned samples with temporal context
    for Stream 1 (Mamba needs sequence input).

    Each sample contains:
        stream1:     [seq_context, 32]  — sequence of consecutive telemetry windows
        stream2_seq: [64, 28]           — action sequence for the last window
        stream2_mask:[64]               — attention mask for Stream 2
        label:       int (0 or 1)       — label of the last window
        window_idx:  int                — position in agent's timeline (for temporal loss)
    """

    def __init__(self, data_dir, agent_ids, seq_context=8, normalize=True,
                 augmentation="none", augmentation_prob=0.0):
        """
        Args:
            data_dir: Directory containing preprocessed .pt files.
            agent_ids: List of agent IDs to include.
            seq_context: Number of consecutive windows for Stream 1 input.
            normalize: Whether to Z-score normalize Stream 1 features.
            augmentation: Augmentation strategy ("none", "feature_mask", "time_jitter").
            augmentation_prob: Probability of applying augmentation per sample.
        """
        self.seq_context = seq_context
        self.augmentation = augmentation
        self.augmentation_prob = augmentation_prob
        self.training_mode = True
        self.data_dir = Path(data_dir)

        # Load all agent data and build index
        self.agent_data = []  # list of per-agent dicts
        self.samples = []     # list of (agent_idx, window_idx) tuples
        self.agent_ids = agent_ids
        for agent_id in agent_ids:
            pt_path = self.data_dir / f"{agent_id}.pt"
            if not pt_path.exists():
                continue
            data = torch.load(pt_path, weights_only=True)
            num_windows = data["stream1"].shape[0]

            # Backfill attack metadata for older .pt files that predate Phase A.
            if "attack_ids" not in data:
                data["attack_ids"] = [""] * num_windows
            if "attack_categories" not in data:
                data["attack_categories"] = [""] * num_windows
            if "attack_id_sets" not in data:
                data["attack_id_sets"] = [[] for _ in range(num_windows)]

            agent_idx = len(self.agent_data)
            self.agent_data.append(data)

            # Need at least seq_context windows to form one sample
            for w in range(seq_context - 1, num_windows):
                self.samples.append((agent_idx, w))

        # Compute normalization stats from all loaded data (training set stats)
        if normalize and self.agent_data:
            all_stream1 = torch.cat([d["stream1"] for d in self.agent_data], dim=0)
            self.stream1_mean = all_stream1.mean(dim=0)
            self.stream1_std = all_stream1.std(dim=0).clamp(min=1e-8)
        else:
            self.stream1_mean = None
            self.stream1_std = None

    def set_normalization_stats(self, mean, std):
        """Set normalization stats from training set (for val/test sets)."""
        self.stream1_mean = mean
        self.stream1_std = std

    def get_normalization_stats(self):
        """Return normalization stats for transfer to val/test sets."""
        return self.stream1_mean, self.stream1_std

    def set_training_mode(self, mode):
        """Enable/disable augmentation (disable for validation/test)."""
        self.training_mode = mode

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        agent_idx, window_idx = self.samples[idx]
        data = self.agent_data[agent_idx]

        # Apply time_jitter: shift context start by +/-1
        effective_window = window_idx
        if (self.training_mode and self.augmentation == "time_jitter"
                and random.random() < self.augmentation_prob):
            jitter = random.choice([-1, 1])
            candidate = window_idx + jitter
            num_windows = data["stream1"].shape[0]
            if self.seq_context - 1 <= candidate < num_windows:
                effective_window = candidate

        # Stream 1: seq_context consecutive windows ending at effective_window
        start = effective_window - self.seq_context + 1
        stream1 = data["stream1"][start:effective_window + 1].clone()  # [seq_context, 32]

        # Normalize Stream 1
        if self.stream1_mean is not None:
            stream1 = (stream1 - self.stream1_mean) / self.stream1_std

        # Stream 2: action sequence for the last window only
        stream2_seq = data["stream2_seq"][effective_window].clone()    # [64, 28]
        stream2_mask = data["stream2_mask"][effective_window]  # [64]

        # Apply feature_mask: randomly zero out 10-30% of features
        if (self.training_mode and self.augmentation == "feature_mask"
                and random.random() < self.augmentation_prob):
            mask_ratio = random.uniform(0.1, 0.3)
            # Mask stream1 features
            s1_mask = torch.rand(stream1.shape[-1]) > mask_ratio
            stream1 = stream1 * s1_mask.unsqueeze(0)
            # Mask stream2 features
            s2_mask = torch.rand(stream2_seq.shape[-1]) > mask_ratio
            stream2_seq = stream2_seq * s2_mask.unsqueeze(0)

        # Label for the last window
        label = data["labels"][effective_window]

        # Primary attack metadata for the effective window (aligned with label)
        attack_id = data["attack_ids"][effective_window]
        attack_category = data["attack_categories"][effective_window]

        return {
            "stream1": stream1,
            "stream2_seq": stream2_seq,
            "stream2_mask": stream2_mask,
            "label": label,
            "window_idx": window_idx,
            "agent_idx": agent_idx,
            "agent_id": self.agent_ids[agent_idx],
            "attack_id": attack_id,
            "attack_category": attack_category,
        }
