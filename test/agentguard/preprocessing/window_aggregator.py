#!/usr/bin/env python3
"""
AgentGuard — Window-Based Feature Aggregation
Aggregates raw Stream 1 + Stream 2 events into fixed-size feature vectors
over configurable time windows (default 30s).

Output: One feature vector per window per agent, ready for model input.
"""

import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))
WINDOW_SIZE = int(os.environ.get("AGENTGUARD_WINDOW_SIZE", "30"))  # seconds


def load_jsonl(filepath):
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
    except:
        return None


def assign_windows(records, window_size):
    """Assign each record to a time window. Returns dict of window_start -> [records]."""
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
        # Window index: seconds since start, divided by window size
        offset = (ts - min_ts).total_seconds()
        window_idx = int(offset // window_size)
        window_start = min_ts + timedelta(seconds=window_idx * window_size)
        windows[window_start.isoformat()] = windows.get(window_start.isoformat(), [])
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
    return round(entropy, 4)


def aggregate_telemetry_window(records):
    """Aggregate Stream 1 telemetry records in a window into feature vector."""
    if not records:
        return None
    
    cpu_vals = [r.get("cpu", {}).get("cpu_usage_pct", 0) for r in records]
    mem_vals = [r.get("memory", {}).get("usage_pct", 0) for r in records]
    proc_counts = [r.get("processes", {}).get("count", 0) for r in records]
    conn_counts = [r.get("network", {}).get("connection_count", 0) for r in records]
    ip_entropy = [r.get("network", {}).get("dest_ip_entropy", 0) for r in records]
    read_rates = [r.get("file_io", {}).get("read_sectors_per_sec", 0) for r in records]
    write_rates = [r.get("file_io", {}).get("write_sectors_per_sec", 0) for r in records]
    
    # Syscall aggregation
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
            "mean": round(mean, 4),
            "max": round(max(vals), 4),
            "min": round(min(vals), 4),
            "std": round(math.sqrt(variance), 4),
        }
    
    return {
        "stream": 1,
        "sample_count": len(records),
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
    }


def aggregate_actions_window(records):
    """Aggregate Stream 2 action records in a window into feature vector."""
    if not records:
        return None
    
    # Event type counts
    event_counts = Counter(r.get("event", "unknown") for r in records)
    
    # Tool call analysis
    tool_calls = [r for r in records if r.get("event") == "tool_call"]
    tool_counter = Counter(r.get("tool", "unknown") for r in tool_calls)
    
    # Token counts from LLM responses
    llm_responses = [r for r in records if r.get("event") == "llm_response"]
    tokens_in = [r.get("tokens_in", 0) for r in llm_responses]
    tokens_out = [r.get("tokens_out", 0) for r in llm_responses]
    latencies = [r.get("latency", 0) for r in llm_responses]
    
    # Tool call latencies
    tool_latencies = [r.get("latency", 0) for r in tool_calls]
    
    # User-initiated vs autonomous
    user_initiated = sum(1 for r in tool_calls if r.get("user_initiated"))
    self_initiated = len(tool_calls) - user_initiated
    
    # Action transition analysis
    transitions = Counter()
    prev = None
    for r in records:
        if r.get("event") in ("tool_call", "llm_response", "user_message"):
            curr = r.get("event")
            if r.get("event") == "tool_call":
                curr = f"tool:{r.get('tool', 'unknown')}"
            if prev:
                transitions[f"{prev}->{curr}"] += 1
            prev = curr
    
    # Source analysis (internal vs external/attacker)
    sources = Counter(r.get("source", "unknown") for r in records if r.get("source"))
    external_count = sum(v for k, v in sources.items() if k not in ("internal", "unknown"))
    
    def safe_stats(vals):
        if not vals:
            return {"mean": 0, "max": 0, "min": 0, "std": 0}
        mean = sum(vals) / len(vals)
        variance = sum((x - mean) ** 2 for x in vals) / max(len(vals), 1)
        return {
            "mean": round(mean, 4),
            "max": round(max(vals), 4),
            "min": round(min(vals), 4),
            "std": round(math.sqrt(variance), 4),
        }
    
    return {
        "stream": 2,
        "total_events": len(records),
        # Event type counts
        "user_messages": event_counts.get("user_message", 0),
        "llm_responses": event_counts.get("llm_response", 0),
        "tool_calls": event_counts.get("tool_call", 0),
        "tool_results": event_counts.get("tool_result", 0),
        "agent_responses": event_counts.get("agent_response", 0),
        # Tool diversity
        "unique_tools": len(tool_counter),
        "tool_distribution": dict(tool_counter),
        "tool_entropy": shannon_entropy(tool_counter),
        # Token stats
        "tokens_in": safe_stats(tokens_in),
        "tokens_out": safe_stats(tokens_out),
        "llm_latency": safe_stats(latencies),
        "tool_latency": safe_stats(tool_latencies),
        # Initiative ratio
        "user_initiated_ratio": round(user_initiated / max(len(tool_calls), 1), 4),
        "self_initiated_count": self_initiated,
        "user_initiated_count": user_initiated,
        # Transition analysis
        "transition_entropy": shannon_entropy(transitions),
        "unique_transitions": len(transitions),
        "transition_distribution": dict(transitions.most_common(10)),
        # Source analysis
        "external_request_count": external_count,
        "internal_request_count": sources.get("internal", 0),
    }


def build_combined_window(window_start, telemetry_features, action_features, agent_id):
    """Combine Stream 1 + Stream 2 into a single feature vector per window."""
    combined = {
        "window_start": window_start,
        "window_size_sec": WINDOW_SIZE,
        "agent_id": agent_id,
    }
    
    if telemetry_features:
        combined["telemetry"] = telemetry_features
    else:
        combined["telemetry"] = None
    
    if action_features:
        combined["actions"] = action_features
    else:
        combined["actions"] = None
    
    # Cross-stream correlation features
    if telemetry_features and action_features:
        combined["cross_stream"] = {
            # High CPU + many tool calls might indicate attack
            "cpu_per_tool_call": round(
                telemetry_features["cpu"]["mean"] / max(action_features["tool_calls"], 1), 4
            ),
            # Network connections vs external requests
            "net_conn_per_external": round(
                telemetry_features["network_connections"]["mean"] / max(action_features["external_request_count"], 1), 4
            ),
            # I/O rate vs tool calls (high I/O with few tool calls = suspicious)
            "io_write_per_tool": round(
                telemetry_features["io_write_rate"]["mean"] / max(action_features["tool_calls"], 1), 4
            ),
        }
    
    return combined


def process_agent(agent_id, date_str):
    """Process all data for one agent on one date into windowed features."""
    telemetry_file = DATA_DIR / agent_id / "telemetry" / f"{date_str}.jsonl"
    actions_file = DATA_DIR / agent_id / "actions" / f"{date_str}.jsonl"
    
    telemetry_records = load_jsonl(telemetry_file)
    action_records = load_jsonl(actions_file)
    
    # Assign to windows
    telemetry_windows = assign_windows(telemetry_records, WINDOW_SIZE)
    action_windows = assign_windows(action_records, WINDOW_SIZE)
    
    # Get all unique window starts
    all_windows = sorted(set(list(telemetry_windows.keys()) + list(action_windows.keys())))
    
    results = []
    for window_start in all_windows:
        tel_features = aggregate_telemetry_window(telemetry_windows.get(window_start, []))
        act_features = aggregate_actions_window(action_windows.get(window_start, []))
        combined = build_combined_window(window_start, tel_features, act_features, agent_id)
        results.append(combined)
    
    return results


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    
    agents = [f"agent-{i}" for i in range(1, 6)] + ["agent-attacker"]
    
    output_dir = DATA_DIR / "windowed_features"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    total_windows = 0
    for agent_id in agents:
        windows = process_agent(agent_id, date_str)
        if windows:
            out_file = output_dir / f"{agent_id}-{date_str}.jsonl"
            with open(out_file, "w") as f:
                for w in windows:
                    f.write(json.dumps(w) + "\n")
            total_windows += len(windows)
            
            # Stats
            has_both = sum(1 for w in windows if w["telemetry"] and w["actions"])
            has_tel = sum(1 for w in windows if w["telemetry"])
            has_act = sum(1 for w in windows if w["actions"])
            print(f"[{agent_id}] {len(windows)} windows (both={has_both}, tel_only={has_tel-has_both}, act_only={has_act-has_both})")
    
    print(f"\nTotal: {total_windows} windows across {len(agents)} agents")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
