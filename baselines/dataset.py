"""Tensor-backed Dataset wrappers for the baseline comparison runner.

Both classes hold pre-built tensors and return (x, label) pairs so the
baseline training loops can be completely decoupled from the rest of the
AgentGuardDataset machinery.
"""

from torch.utils.data import Dataset


class FlatTensorDataset(Dataset):
    """Serves per-window flat feature vectors. x[i] has shape [F]."""

    def __init__(self, x, labels):
        self.x = x
        self.labels = labels

    def __len__(self):
        return int(self.x.shape[0])

    def __getitem__(self, i):
        return self.x[i], self.labels[i]


class SeqTensorDataset(Dataset):
    """Serves per-window sequence tensors. seq[i] has shape [T, F]."""

    def __init__(self, seq, labels):
        self.seq = seq
        self.labels = labels

    def __len__(self):
        return int(self.seq.shape[0])

    def __getitem__(self, i):
        return self.seq[i], self.labels[i]
