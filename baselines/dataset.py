import torch
from torch.utils.data import Dataset


class SeqTensorDataset(Dataset):
    """Wraps a precomputed [M, T, D] tensor and [M] labels."""

    def __init__(self, seq: torch.Tensor, labels: torch.Tensor):
        assert seq.dim() == 3 and labels.dim() == 1 and seq.shape[0] == labels.shape[0]
        self.seq = seq
        self.labels = labels

    def __len__(self):
        return self.seq.shape[0]

    def __getitem__(self, i):
        return self.seq[i], self.labels[i]


class FlatTensorDataset(Dataset):
    """Wraps a precomputed [M, D] tensor and [M] labels."""

    def __init__(self, flat: torch.Tensor, labels: torch.Tensor):
        assert flat.dim() == 2 and labels.dim() == 1 and flat.shape[0] == labels.shape[0]
        self.flat = flat
        self.labels = labels

    def __len__(self):
        return self.flat.shape[0]

    def __getitem__(self, i):
        return self.flat[i], self.labels[i]
