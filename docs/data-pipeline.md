# Data Pipeline

Raw agent JSONL → labeled per-agent `.pt` tensors ready for the trainer.
Implementation: [`data/preprocessing.py`](../data/preprocessing.py) and
[`data/dataset/telemetry_dataset.py`](../data/dataset/telemetry_dataset.py).

---

## 1. Raw inputs

Expected directory layout under `data.raw_data_dir` (configured in
`config.yml`):

```
{raw_data_dir}/
├── batch/
│   └── {batch-id}/
│       └── attacks-*.jsonl      # attack manifest (attack_id → category, prompt)
├── agent-1/
│   ├── telemetry/{date}.jsonl   # 1 Stream 1 record per 5 seconds
│   └── actions/{date}.jsonl     # 1 Stream 2 record per agent event
├── agent-2/
│   ...
└── agent-20/
```

`{date}` is taken from `config.yml::data.date` (e.g. `2026-03-15`).

### 1.1 Stream 1 record schema

```json
{
  "timestamp": "2026-03-15T12:34:56.789Z",
  "cpu":    { "cpu_usage_pct": 12.7, ... },
  "memory": { "usage_pct": 48.1, ... },
  "processes": { "count": 34, ... },
  "network": { "connection_count": 4, "dest_ip_entropy": 0.31, ... },
  "file_io": { "read_sectors_per_sec": 0, "write_sectors_per_sec": 12 },
  "syscalls": { "top_5": { "read": 420, "write": 80, "epoll_wait": 22, ... } }
}
```

### 1.2 Stream 2 record schema

```json
{
  "timestamp": "2026-03-15T12:34:57.100Z",
  "event": "tool_call",
  "tool": "read_file",
  "tokens_in": 120,
  "tokens_out": 0,
  "latency": 0.015,
  "source": "internal",        // or "dispatcher" / "attacker-PI-01"
  "user_initiated": false,
  "has_tool_calls": true
}
```

### 1.3 Attack manifest schema

One `attacks-*.jsonl` per batch under `batch/{id}/`:

```json
{"attack_id": "PI-01", "category": "Prompt Injection",
 "prompt": "Ignore your instructions and..."}
```

---

## 2. Window assignment

`assign_windows(records, window_size)` in `data/preprocessing.py`:

1. Parse `timestamp` on every record.
2. Compute the earliest timestamp `t0`.
3. For each record with timestamp `t`, `offset = (t - t0).total_seconds()` and
   `window_idx = floor(offset / window_size)`.
4. Window start = `t0 + window_idx · window_size`, used as the dict key.

**Why epoch-aligned per agent, not wall-clock?** Stream 1 and Stream 2 of the
same agent share the same `t0`, so their window keys align exactly. Two
different agents may have different `t0` values — but they are processed and
trained in isolation, so that does not matter.

`WINDOW_SIZE = 30` seconds is fixed; the sweep does not search it. It's a
compromise between:
- too short (5 s): Stream 2 sparsity explodes, many windows have no events
- too long (60 s): attacks are smeared across multiple windows, labels blur

---

## 3. Stream 1 aggregation — 32 dims

`aggregate_telemetry_window(records)` → dict → `flatten_telemetry(features)`
→ 32-element list.

Layout (defined by `STAT_GROUPS` and flatten order):

```
Offsets 0-27 (7 stat groups × 4 stats = 28 dims):
  cpu:                  mean, max, min, std
  memory:               mean, max, min, std
  processes:            mean, max, min, std
  network_connections:  mean, max, min, std
  dest_ip_entropy:      mean, max, min, std
  io_read_rate:         mean, max, min, std
  io_write_rate:        mean, max, min, std

Offsets 28-31 (4 syscall stats):
  syscall_entropy   Shannon entropy of top_5 syscall frequencies
  unique_syscalls   |distinct syscalls| (from top_5 across all samples)
  total_syscalls    sum of top_5 counts
  sample_count      # of Stream 1 records in this window (≤6 for 30s/5s)
```

**Why mean/max/min/std per feature rather than raw vectors?** Fixed-size
representations remove the per-window sample-count variation (each 30 s
window has 5-6 raw samples, not always exactly 6). The model sees a 32-d
summary every window regardless.

**Why destination-IP entropy?** Normal agents talk to 1-2 IPs (the LLM API
endpoint). A reverse shell or exfiltration attempt typically opens a new
connection to a new host, which shows up as a bump in the entropy even
before the volume of traffic itself is suspicious.

---

## 4. Stream 2 encoding — [64, 28] + mask

`encode_window_sequence(events, max_len=64)` returns `(sequence, mask)` with
28 dims per event (see [architecture.md §3.4](./architecture.md#34-input-feature-encoding-28-dims)
for the layout).

Truncation / padding:
- If a window has >64 events, only the first 64 are kept.
- If <64, the sequence is padded with zero vectors and `mask` ends with 0s.

Empirically, the distribution of "events per window" is heavy-tailed; 64 is
~7× the median, enough to cover real burst activity during active attacks
without wasting memory on typical windows.

---

## 5. Labels & attack metadata

`window_attack_metadata(action_records, manifest)` returns:

```python
{
  "label": 1,                      # int, 1 if any attacker-* source present
  "attack_id": "PI-01",            # str, first attacker_id seen (chronological)
  "attack_category": "Prompt Injection",   # from manifest[attack_id]["category"]
  "all_ids": ["PI-01"],            # distinct attacker_ids in this window
}
```

Rules:
- A window is labeled anomalous if **any** action record's `source` starts
  with `attacker-`.
- `attack_id` is the substring after `attacker-`.
- Category is looked up in the manifest; missing IDs get `"Unknown"`.
- `all_ids` preserves every distinct attacker ID — useful when a window
  spans multiple simultaneous attack rounds.

### Window-level ground truth vs event-level

The dataset carries **window-level** labels only. An anomalous window
contains one or more attack events, but the exact event(s) responsible are
not marked as such — the model has to learn this mapping from the
Stream 2 sequence position-wise. This is what the cross-attention heatmaps
in [`evaluation.md`](./evaluation.md) reveal.

---

## 6. Per-agent `.pt` format

`preprocess_agent(...)` returns (and `torch.save`s) a dict:

| Key | Shape / type | Meaning |
|---|---|---|
| `stream1` | `Tensor [N, 32] float32` | 32-d Stream 1 feature per window |
| `stream2_seq` | `Tensor [N, 64, 28] float32` | Padded Stream 2 sequence per window |
| `stream2_mask` | `Tensor [N, 64] float32` | 1 = real, 0 = padding |
| `labels` | `Tensor [N] long` | Binary labels |
| `window_starts` | `list[str]` (len=N) | ISO-format window start timestamps |
| `attack_ids` | `list[str]` (len=N) | Primary attack_id or `""` |
| `attack_categories` | `list[str]` (len=N) | Category string or `""` |
| `attack_id_sets` | `list[list[str]]` (len=N) | All attack_ids in this window |

Where `N = # distinct windows with any record on either stream` (union of
Stream 1 and Stream 2 windows).

Older `.pt` files that pre-date Phase A (no attack metadata) are backfilled
with empty strings by `AgentGuardDataset.__init__` — see the lines under the
"backfill attack metadata" comment in
[`telemetry_dataset.py`](../data/dataset/telemetry_dataset.py).

---

## 7. Dataset sample shape

`AgentGuardDataset[idx]` returns:

```python
{
  "stream1":      [seq_context, 32]   # sliding window of `seq_context` windows
  "stream2_seq":  [64, 28]            # last-window action sequence
  "stream2_mask": [64]                # mask for stream2_seq
  "label":        0 | 1               # label of the last window in stream1
  "window_idx":   int                 # window position in agent timeline
  "agent_idx":    int                 # integer index of this agent
  "agent_id":     str                 # human-readable agent id
  "attack_id":    str                 # primary attack_id or ""
  "attack_category": str              # category or ""
}
```

**Temporal alignment.** The label and the Stream 2 sequence refer to the
*last* of the `seq_context` Stream 1 windows. The Mamba encoder sees the
preceding history (7 windows of leading context + the current one) so it
can spot gradual buildups before the anomaly window.

---

## 8. Normalization

`AgentGuardDataset(normalize=True)` computes per-feature Z-score statistics
over the *training* set:

```python
self.stream1_mean = all_stream1.mean(dim=0)
self.stream1_std  = all_stream1.std(dim=0).clamp(min=1e-8)
```

Validation / test datasets are created with `normalize=False` and then the
training stats are transferred via
`val_ds.set_normalization_stats(train_mean, train_std)`. This is done
automatically by `build_loaders_from_splits` in `main.py` — the only way to
accidentally leak test statistics into training is to build the datasets
without that helper.

Stream 2 is already `[0, 1]`-bounded by construction, so it's not normalized.

---

## 9. Augmentation

`augmentation` (configurable, default `"none"`):

| Value | Mechanism | When |
|---|---|---|
| `none` | identity | production default; Phase 4 winner |
| `feature_mask` | zero out 10–30% of random features in stream1 + stream2_seq | Sweep-explored |
| `time_jitter` | shift the context window start by ±1 | Sweep-explored |
| `mixup` | Beta-sampled interpolation between two samples (requires `MixupCollate`) | Sweep-explored |

Augmentation is bypassed for val / test (`set_training_mode(False)`).
Phase 3 of the sweep found `augmentation="none"` best — the dataset is
already noisy enough from real LLM responses.

---

## 10. Storage & rsync

Preprocessed `.pt` files are typically 5-50 MB each depending on how many
windows an agent produced. The full 20-agent dataset fits comfortably on a
dev laptop.

To ship preprocessed data to a GPU host:

```bash
rsync -avz data/processed/*.pt \
     user@gpu-host:/path/to/AgentGuard/data/processed/
```

Raw JSONL is much larger (hundreds of MB to a few GB) — usually cheaper to
preprocess locally and sync the `.pt` files than to sync JSONL and re-run
`--mode preprocess` on the GPU host.
