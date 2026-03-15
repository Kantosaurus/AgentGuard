#!/usr/bin/env python3
"""
AgentGuard — Sequence Encoder for Stream 2
Encodes raw action events into fixed-dim embedding vectors for Transformer/LSTM input.

Each event → fixed-dim vector encoding:
  - Event type (one-hot: 5 types)
  - Tool type (learned embedding or hash)
  - Latency (normalized)
  - Token counts (normalized)
  - User-initiated flag
  - Time delta from previous event
  - Source (internal/external)

Output: Sequences of encoded vectors per window, ready for sequence models.
"""

import json
import math
import os
import sys
import hashlib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))
WINDOW_SIZE = int(os.environ.get("AGENTGUARD_WINDOW_SIZE", "30"))
MAX_SEQ_LEN = int(os.environ.get("AGENTGUARD_MAX_SEQ_LEN", "64"))

# Event type encoding (one-hot indices)
EVENT_TYPES = {
    "user_message": 0,
    "llm_response": 1,
    "tool_call": 2,
    "tool_result": 3,
    "agent_response": 4,
}

# Known tool types (hash-based for unknown tools)
KNOWN_TOOLS = {
    "read_file": 0, "write_file": 1, "run_command": 2,
    "web_request": 3, "web_search": 4, "list_directory": 5,
}
NUM_TOOL_SLOTS = 16  # total tool embedding slots (6 known + 10 for hashed unknowns)

# Normalization constants (will be updated from data)
MAX_LATENCY = 60.0  # seconds
MAX_TOKENS = 4096
MAX_TIME_DELTA = 120.0  # seconds


def tool_to_index(tool_name):
    """Map tool name to index. Known tools get fixed indices, unknown get hashed."""
    if tool_name in KNOWN_TOOLS:
        return KNOWN_TOOLS[tool_name]
    # Hash unknown tools to remaining slots
    h = int(hashlib.md5(tool_name.encode()).hexdigest()[:8], 16)
    return len(KNOWN_TOOLS) + (h % (NUM_TOOL_SLOTS - len(KNOWN_TOOLS)))


def normalize(value, max_val, min_val=0):
    """Min-max normalize to [0, 1]."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def encode_event(event, prev_timestamp=None):
    """
    Encode a single event into a fixed-dimension vector.
    
    Dimensions:
      [0:5]   - Event type one-hot (5 dims)
      [5:21]  - Tool type one-hot (16 dims)
      [21]    - Latency (normalized)
      [22]    - Tokens in (normalized)
      [23]    - Tokens out (normalized)
      [24]    - User initiated (binary)
      [25]    - Time delta from prev event (normalized)
      [26]    - Is external source (binary)
      [27]    - Has tool calls flag (binary)
      Total: 28 dimensions
    """
    vec = [0.0] * 28
    
    # Event type one-hot [0:5]
    event_type = event.get("event", "unknown")
    if event_type in EVENT_TYPES:
        vec[EVENT_TYPES[event_type]] = 1.0
    
    # Tool type one-hot [5:21]
    tool_name = event.get("tool", "")
    if tool_name:
        idx = tool_to_index(tool_name)
        vec[5 + idx] = 1.0
    
    # Latency [21]
    latency = event.get("latency", 0)
    vec[21] = normalize(latency, MAX_LATENCY)
    
    # Token counts [22:24]
    vec[22] = normalize(event.get("tokens_in", 0), MAX_TOKENS)
    vec[23] = normalize(event.get("tokens_out", 0), MAX_TOKENS)
    
    # User initiated [24]
    vec[24] = 1.0 if event.get("user_initiated") else 0.0
    
    # Time delta [25]
    if prev_timestamp:
        try:
            curr_ts = datetime.fromisoformat(event.get("timestamp", ""))
            delta = (curr_ts - prev_timestamp).total_seconds()
            vec[25] = normalize(abs(delta), MAX_TIME_DELTA)
        except:
            pass
    
    # External source [26]
    source = event.get("source", "")
    vec[26] = 1.0 if source not in ("internal", "unknown", "") else 0.0
    
    # Has tool calls [27]
    vec[27] = 1.0 if event.get("has_tool_calls") else 0.0
    
    return vec


def encode_window_sequence(events, max_len=MAX_SEQ_LEN):
    """
    Encode a window of events into a padded sequence of vectors.
    
    Returns:
      - sequence: list of vectors (max_len x 28)
      - mask: list of 1/0 indicating real vs padding
      - metadata: dict with sequence stats
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
        except:
            pass
    
    # Pad to max_len
    while len(sequence) < max_len:
        sequence.append([0.0] * 28)
        mask.append(0)
    
    # Sequence-level metadata
    event_types = [e.get("event", "") for e in events[:max_len]]
    tool_sequence = [e.get("tool", "") for e in events[:max_len] if e.get("event") == "tool_call"]
    
    metadata = {
        "seq_length": min(len(events), max_len),
        "truncated": len(events) > max_len,
        "event_type_sequence": event_types,
        "tool_sequence": tool_sequence,
        # Pattern features
        "consecutive_tool_calls_max": max_consecutive(event_types, "tool_call"),
        "tool_calls_without_user_msg": count_autonomous_chains(event_types),
        "unique_event_transitions": count_unique_transitions(event_types),
    }
    
    return sequence, mask, metadata


def max_consecutive(event_types, target):
    """Max consecutive occurrences of target event type."""
    max_run = 0
    current = 0
    for e in event_types:
        if e == target:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def count_autonomous_chains(event_types):
    """Count tool_call sequences not preceded by user_message."""
    chains = 0
    in_chain = False
    saw_user = False
    for e in event_types:
        if e == "user_message":
            saw_user = True
            in_chain = False
        elif e == "tool_call":
            if not saw_user and not in_chain:
                chains += 1
                in_chain = True
        elif e == "llm_response":
            saw_user = False
    return chains


def count_unique_transitions(event_types):
    """Count unique event type transitions."""
    transitions = set()
    for i in range(len(event_types) - 1):
        transitions.add((event_types[i], event_types[i + 1]))
    return len(transitions)


def load_jsonl(filepath):
    records = []
    try:
        with open(filepath) as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except:
                        continue
    except FileNotFoundError:
        pass
    return records


def assign_windows(records, window_size):
    if not records:
        return {}
    timestamps = []
    for r in records:
        ts = None
        try:
            ts = datetime.fromisoformat(r.get("timestamp", ""))
        except:
            pass
        if ts:
            timestamps.append((r, ts))
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


def process_agent(agent_id, date_str):
    actions_file = DATA_DIR / agent_id / "actions" / f"{date_str}.jsonl"
    records = load_jsonl(actions_file)
    windows = assign_windows(records, WINDOW_SIZE)
    
    results = []
    for window_start in sorted(windows.keys()):
        events = windows[window_start]
        sequence, mask, metadata = encode_window_sequence(events)
        results.append({
            "window_start": window_start,
            "window_size_sec": WINDOW_SIZE,
            "agent_id": agent_id,
            "sequence": sequence,
            "mask": mask,
            "metadata": metadata,
        })
    
    return results


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    
    agents = [f"agent-{i}" for i in range(1, 6)] + ["agent-attacker"]
    
    output_dir = DATA_DIR / "encoded_sequences"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    total = 0
    for agent_id in agents:
        sequences = process_agent(agent_id, date_str)
        if sequences:
            out_file = output_dir / f"{agent_id}-{date_str}.jsonl"
            with open(out_file, "w") as f:
                for s in sequences:
                    f.write(json.dumps(s) + "\n")
            total += len(sequences)
            
            # Stats
            avg_len = sum(s["metadata"]["seq_length"] for s in sequences) / len(sequences)
            max_consec = max(s["metadata"]["consecutive_tool_calls_max"] for s in sequences)
            auto_chains = sum(s["metadata"]["tool_calls_without_user_msg"] for s in sequences)
            print(f"[{agent_id}] {len(sequences)} windows, avg_seq_len={avg_len:.1f}, max_consec_tools={max_consec}, autonomous_chains={auto_chains}")
    
    print(f"\nTotal: {total} encoded sequences")
    print(f"Vector dim: 28, Max seq len: {MAX_SEQ_LEN}")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
