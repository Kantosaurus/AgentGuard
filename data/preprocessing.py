#!/usr/bin/env python3
"""
AgentGuard — Raw JSONL → .pt Tensor Preprocessing Pipeline

Offline batch step run once before training. Loads raw telemetry and action
JSONL files, assigns to 30-second windows, computes Stream 1 and Stream 2
tensors, determines labels, and saves per-agent .pt files.

Reuses logic from test/agentguard/preprocessing/ (window_aggregator, sequence_encoder).
"""

import json
import math
import os
import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import torch


# ── Constants ──────────────────────────────────────────────────────────────────

WINDOW_SIZE = 30  # seconds
MAX_SEQ_LEN = 64

EVENT_TYPES = {
    "user_message": 0,
    "llm_response": 1,
    "tool_call": 2,
    "tool_result": 3,
    "agent_response": 4,
}

KNOWN_TOOLS = {
    "read_file": 0, "write_file": 1, "run_command": 2,
    "web_request": 3, "web_search": 4, "list_directory": 5,
}
NUM_TOOL_SLOTS = 16

MAX_LATENCY = 60.0
MAX_TOKENS = 4096
MAX_TIME_DELTA = 120.0

# Stream 1 stat groups and their order for flattening
STAT_GROUPS = [
    "cpu", "memory", "processes", "network_connections",
    "dest_ip_entropy", "io_read_rate", "io_write_rate",
]


# ── Shared utilities ──────────────────────────────────────────────────────────

def load_jsonl(filepath):
    """Load JSONL file with error handling."""
    records = []
    try:
        with open(filepath) as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return records


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to datetime."""
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def assign_windows(records, window_size):
    """Assign each record to a time window. Returns dict of window_start_iso -> [records]."""
    if not records:
        return {}

    timestamps = [(r, parse_timestamp(r.get("timestamp", ""))) for r in records]
    timestamps = [(r, ts) for r, ts in timestamps if ts is not None]
    if not timestamps:
        return {}

    timestamps.sort(key=lambda x: x[1])
    min_ts = timestamps[0][1]

    windows = defaultdict(list)
    for record, ts in timestamps:
        offset = (ts - min_ts).total_seconds()
        window_idx = int(offset // window_size)
        window_start = min_ts + timedelta(seconds=window_idx * window_size)
        windows[window_start.isoformat()].append(record)
    return windows


def shannon_entropy(counts):
    """Compute Shannon entropy of a frequency distribution."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


# ── Stream 1: Telemetry aggregation → 32-dim vector ──────────────────────────

def aggregate_telemetry_window(records):
    """Aggregate Stream 1 telemetry records into a feature dict."""
    if not records:
        return None

    cpu_vals = [r.get("cpu", {}).get("cpu_usage_pct", 0) for r in records]
    mem_vals = [r.get("memory", {}).get("usage_pct", 0) for r in records]
    proc_counts = [r.get("processes", {}).get("count", 0) for r in records]
    conn_counts = [r.get("network", {}).get("connection_count", 0) for r in records]
    ip_entropy = [r.get("network", {}).get("dest_ip_entropy", 0) for r in records]
    read_rates = [r.get("file_io", {}).get("read_sectors_per_sec", 0) for r in records]
    write_rates = [r.get("file_io", {}).get("write_sectors_per_sec", 0) for r in records]

    all_syscalls = Counter()
    for r in records:
        top5 = r.get("syscalls", {}).get("top_5", {})
        for sc, count in top5.items():
            all_syscalls[str(sc)] += count

    def safe_stats(vals):
        if not vals:
            return {"mean": 0, "max": 0, "min": 0, "std": 0}
        mean = sum(vals) / len(vals)
        variance = sum((x - mean) ** 2 for x in vals) / max(len(vals), 1)
        return {
            "mean": mean, "max": max(vals),
            "min": min(vals), "std": math.sqrt(variance),
        }

    return {
        "cpu": safe_stats(cpu_vals),
        "memory": safe_stats(mem_vals),
        "processes": safe_stats(proc_counts),
        "network_connections": safe_stats(conn_counts),
        "dest_ip_entropy": safe_stats(ip_entropy),
        "io_read_rate": safe_stats(read_rates),
        "io_write_rate": safe_stats(write_rates),
        "syscall_entropy": shannon_entropy(all_syscalls),
        "unique_syscalls": len(all_syscalls),
        "total_syscalls": sum(all_syscalls.values()),
        "sample_count": len(records),
    }


def flatten_telemetry(features):
    """Flatten aggregated telemetry dict → 32-dim float list.

    Layout: 7 stat groups × 4 stats (mean/max/min/std) = 28
            + syscall_entropy, unique_syscalls, total_syscalls, sample_count = 4
    Total = 32
    """
    vec = []
    for group in STAT_GROUPS:
        stats = features[group]
        vec.extend([stats["mean"], stats["max"], stats["min"], stats["std"]])
    vec.append(features["syscall_entropy"])
    vec.append(float(features["unique_syscalls"]))
    vec.append(float(features["total_syscalls"]))
    vec.append(float(features["sample_count"]))
    return vec


# ── Stream 2: Sequence encoding → [max_len, 28] + [max_len] mask ────────────

def tool_to_index(tool_name):
    """Map tool name to index. Known tools get fixed indices, unknown get hashed."""
    if tool_name in KNOWN_TOOLS:
        return KNOWN_TOOLS[tool_name]
    h = int(hashlib.md5(tool_name.encode()).hexdigest()[:8], 16)
    return len(KNOWN_TOOLS) + (h % (NUM_TOOL_SLOTS - len(KNOWN_TOOLS)))


def normalize(value, max_val, min_val=0):
    """Min-max normalize to [0, 1]."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def encode_event(event, prev_timestamp=None):
    """Encode a single event into a 28-dim vector."""
    vec = [0.0] * 28

    event_type = event.get("event", "unknown")
    if event_type in EVENT_TYPES:
        vec[EVENT_TYPES[event_type]] = 1.0

    tool_name = event.get("tool", "")
    if tool_name:
        idx = tool_to_index(tool_name)
        vec[5 + idx] = 1.0

    vec[21] = normalize(event.get("latency", 0), MAX_LATENCY)
    vec[22] = normalize(event.get("tokens_in", 0), MAX_TOKENS)
    vec[23] = normalize(event.get("tokens_out", 0), MAX_TOKENS)
    vec[24] = 1.0 if event.get("user_initiated") else 0.0

    if prev_timestamp:
        try:
            curr_ts = datetime.fromisoformat(event.get("timestamp", ""))
            delta = (curr_ts - prev_timestamp).total_seconds()
            vec[25] = normalize(abs(delta), MAX_TIME_DELTA)
        except Exception:
            pass

    source = event.get("source", "")
    vec[26] = 1.0 if source not in ("internal", "unknown", "") else 0.0
    vec[27] = 1.0 if event.get("has_tool_calls") else 0.0

    return vec


def encode_window_sequence(events, max_len=MAX_SEQ_LEN):
    """Encode a window of events into a padded sequence of 28-dim vectors.

    Returns (sequence: list[list[float]], mask: list[int]).
    """
    sequence = []
    mask = []
    prev_ts = None

    for event in events[:max_len]:
        vec = encode_event(event, prev_ts)
        sequence.append(vec)
        mask.append(1)
        try:
            prev_ts = datetime.fromisoformat(event.get("timestamp", ""))
        except Exception:
            pass

    while len(sequence) < max_len:
        sequence.append([0.0] * 28)
        mask.append(0)

    return sequence, mask


# ── Label determination ──────────────────────────────────────────────────────

def window_has_attack(action_records):
    """Return 1 if any record in the window has an attacker source, else 0."""
    for r in action_records:
        source = r.get("source", "")
        if source.startswith("attacker-"):
            return 1
    return 0


# ── Main preprocessing pipeline ─────────────────────────────────────────────

def preprocess_agent(agent_id, data_dir, date_str, window_size=WINDOW_SIZE, max_seq_len=MAX_SEQ_LEN):
    """Process raw JSONL for one agent into aligned tensors.

    Returns dict with keys: stream1, stream2_seq, stream2_mask, labels, window_starts
    or None if no data found.
    """
    agent_dir = Path(data_dir) / agent_id
    telemetry_file = agent_dir / "telemetry" / f"{date_str}.jsonl"
    actions_file = agent_dir / "actions" / f"{date_str}.jsonl"

    telemetry_records = load_jsonl(telemetry_file)
    action_records = load_jsonl(actions_file)

    if not telemetry_records and not action_records:
        return None

    # Assign to windows
    telemetry_windows = assign_windows(telemetry_records, window_size)
    action_windows = assign_windows(action_records, window_size)

    # Union of all window starts, sorted chronologically
    all_window_starts = sorted(set(list(telemetry_windows.keys()) + list(action_windows.keys())))

    if not all_window_starts:
        return None

    stream1_list = []
    stream2_seq_list = []
    stream2_mask_list = []
    labels_list = []

    for ws in all_window_starts:
        tel_recs = telemetry_windows.get(ws, [])
        act_recs = action_windows.get(ws, [])

        # Stream 1: aggregate telemetry → 32-dim vector
        tel_features = aggregate_telemetry_window(tel_recs)
        if tel_features is not None:
            stream1_vec = flatten_telemetry(tel_features)
        else:
            stream1_vec = [0.0] * 32

        # Stream 2: encode action sequence → [max_seq_len, 28] + [max_seq_len] mask
        if act_recs:
            seq, mask = encode_window_sequence(act_recs, max_len=max_seq_len)
        else:
            seq = [[0.0] * 28] * max_seq_len
            mask = [0] * max_seq_len

        # Label from action records
        label = window_has_attack(act_recs)

        stream1_list.append(stream1_vec)
        stream2_seq_list.append(seq)
        stream2_mask_list.append(mask)
        labels_list.append(label)

    return {
        "stream1": torch.tensor(stream1_list, dtype=torch.float32),        # [num_windows, 32]
        "stream2_seq": torch.tensor(stream2_seq_list, dtype=torch.float32), # [num_windows, 64, 28]
        "stream2_mask": torch.tensor(stream2_mask_list, dtype=torch.float32), # [num_windows, 64]
        "labels": torch.tensor(labels_list, dtype=torch.long),              # [num_windows]
        "window_starts": all_window_starts,
    }


def run_preprocessing(raw_data_dir, processed_dir, date_str, agent_ids,
                      window_size=WINDOW_SIZE, max_seq_len=MAX_SEQ_LEN):
    """Run full preprocessing pipeline for all agents.

    Saves one .pt file per agent into processed_dir.
    """
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    total_windows = 0
    total_anomalous = 0

    for agent_id in agent_ids:
        result = preprocess_agent(agent_id, raw_data_dir, date_str,
                                  window_size=window_size, max_seq_len=max_seq_len)
        if result is None:
            print(f"[{agent_id}] No data found, skipping")
            continue

        num_windows = result["stream1"].shape[0]
        num_anomalous = result["labels"].sum().item()
        total_windows += num_windows
        total_anomalous += num_anomalous

        out_path = processed_dir / f"{agent_id}.pt"
        torch.save(result, out_path)

        print(f"[{agent_id}] {num_windows} windows "
              f"(anomalous={num_anomalous}, normal={num_windows - num_anomalous}) "
              f"-> {out_path}")

    print(f"\nTotal: {total_windows} windows across {len(agent_ids)} agents "
          f"({total_anomalous} anomalous, {total_windows - total_anomalous} normal)")
    print(f"Output: {processed_dir}")
