import numpy as np
from torch.utils.data import Dataset

class ActionSequenceDataset(Dataset):
    def __init__(self, data: np.ndarray):
        self.data = data

    def __len__(self):
        pass

    def __getitem__(self, idx):
        pass