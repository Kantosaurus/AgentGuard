"""
Baseline feature utilities.

Provides build_agent_features and build_fold_tensors used by all baseline methods.
"""

from pathlib import Path

import torch


def build_agent_features(
    data_dir: "Path | str", agent_id: str
) -> "tuple[torch.Tensor, torch.Tensor]":
    """Load the preprocessed .pt file for one agent and return
    (features [N, 60], labels [N]).
    features[i] = concat(stream1[i], masked_mean_pool(stream2_seq[i], stream2_mask[i])).
    labels[i]   = labels[i] (int).
    """
    path = Path(data_dir) / f"{agent_id}.pt"
    data = torch.load(path, weights_only=True)

    stream1 = data["stream1"]          # [N, 32]
    stream2_seq = data["stream2_seq"]  # [N, 64, 28]
    stream2_mask = data["stream2_mask"]  # [N, 64]
    labels = data["labels"]            # [N]

    N = stream1.shape[0]
    assert stream1.shape == (N, 32), f"Unexpected stream1 shape: {stream1.shape}"
    assert stream2_seq.shape == (N, 64, 28), f"Unexpected stream2_seq shape: {stream2_seq.shape}"
    assert stream2_mask.shape == (N, 64), f"Unexpected stream2_mask shape: {stream2_mask.shape}"

    denom = stream2_mask.sum(dim=1, keepdim=True).clamp(min=1.0)            # [N, 1]
    pooled = (stream2_seq * stream2_mask.unsqueeze(-1)).sum(dim=1) / denom  # [N, 28]

    features = torch.cat([stream1, pooled], dim=-1).float()  # [N, 60]
    assert features.shape == (N, 60), f"Unexpected features shape: {features.shape}"

    return features, labels


def build_fold_tensors(
    data_dir,
    train_ids,
    val_ids,
    test_ids,
    seq_context: int = 8,
) -> dict:
    """Returns a dict with keys 'train', 'val', 'test'. Each value is another
    dict: {'seq': FloatTensor [M, seq_context, 60], 'flat': FloatTensor [M, seq_context*60],
           'labels': LongTensor [M], 'agents': list[str] of length M}.
    Also returns 'mean' [60], 'std' [60] fit on TRAINING flat windows only.
    """
    def _slide(feat, lbl, agent_id):
        N = feat.shape[0]
        seqs, labels, agents = [], [], []
        for w in range(seq_context - 1, N):
            seqs.append(feat[w - seq_context + 1 : w + 1])  # [seq_context, 60]
            labels.append(lbl[w])
            agents.append(agent_id)
        if not seqs:
            return None, None, []
        return torch.stack(seqs, dim=0), torch.stack(labels, dim=0), agents

    def _build_split(ids):
        all_seq, all_lbl, all_agents = [], [], []
        for agent_id in ids:
            feat, lbl = build_agent_features(data_dir, agent_id)
            seq, labels, agents = _slide(feat, lbl, agent_id)
            if seq is None:
                continue
            all_seq.append(seq)
            all_lbl.append(labels)
            all_agents.extend(agents)
        if not all_seq:
            seq_t = torch.zeros(0, seq_context, 60)
            lbl_t = torch.zeros(0, dtype=torch.long)
            return seq_t, lbl_t, []
        return torch.cat(all_seq, dim=0), torch.cat(all_lbl, dim=0), all_agents

    seq_train, lbl_train, agents_train = _build_split(train_ids)
    seq_val, lbl_val, agents_val = _build_split(val_ids)
    seq_test, lbl_test, agents_test = _build_split(test_ids)

    flat_train = seq_train.reshape(-1, 60)  # [M*seq_context, 60]
    if flat_train.shape[0] == 0:
        raise ValueError("train split produced no windows; cannot fit normalization stats")
    mean = flat_train.mean(dim=0)           # [60]
    std = flat_train.std(dim=0, correction=0).clamp(min=1e-8)  # [60]

    seq_train = (seq_train - mean) / std
    seq_val = (seq_val - mean) / std
    seq_test = (seq_test - mean) / std

    M_train = seq_train.shape[0]
    M_val = seq_val.shape[0]
    M_test = seq_test.shape[0]

    return {
        "train": {
            "seq": seq_train,
            "flat": seq_train.reshape(M_train, seq_context * 60),
            "labels": lbl_train.long(),
            "agents": agents_train,
        },
        "val": {
            "seq": seq_val,
            "flat": seq_val.reshape(M_val, seq_context * 60),
            "labels": lbl_val.long(),
            "agents": agents_val,
        },
        "test": {
            "seq": seq_test,
            "flat": seq_test.reshape(M_test, seq_context * 60),
            "labels": lbl_test.long(),
            "agents": agents_test,
        },
        "mean": mean,
        "std": std,
    }
