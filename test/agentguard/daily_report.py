#!/usr/bin/env python3
"""
AgentGuard — Daily Report Generator
Summarizes telemetry and action data from the past 24h.
Outputs a JSON report for Telegram delivery.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))


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


def summarize_telemetry(date_str):
    records = load_jsonl(DATA_DIR / "telemetry" / f"{date_str}.jsonl")
    if not records:
        return None

    cpu_vals = [r["cpu"].get("cpu_usage_pct", 0) for r in records if "cpu_usage_pct" in r.get("cpu", {})]
    mem_vals = [r["memory"].get("usage_pct", 0) for r in records if "usage_pct" in r.get("memory", {})]
    conn_counts = [r["network"].get("connection_count", 0) for r in records if "connection_count" in r.get("network", {})]
    entropy_vals = [r["network"].get("dest_ip_entropy", 0) for r in records if "dest_ip_entropy" in r.get("network", {})]
    proc_counts = [r["processes"].get("count", 0) for r in records if "count" in r.get("processes", {})]

    def stats(vals):
        if not vals:
            return {"avg": 0, "min": 0, "max": 0}
        return {"avg": round(sum(vals)/len(vals), 2), "min": round(min(vals), 2), "max": round(max(vals), 2)}

    return {
        "samples": len(records),
        "cpu_pct": stats(cpu_vals),
        "memory_pct": stats(mem_vals),
        "network_connections": stats(conn_counts),
        "dest_ip_entropy": stats(entropy_vals),
        "process_count": stats(proc_counts),
    }


def summarize_actions(date_str):
    records = load_jsonl(DATA_DIR / "actions" / f"{date_str}.jsonl")
    if not records:
        return None

    tool_calls = [r for r in records if r.get("event") == "tool_call"]
    llm_calls = [r for r in records if r.get("event") == "llm_response"]
    user_msgs = [r for r in records if r.get("event") == "user_message"]

    tool_counter = Counter(r.get("tool", "unknown") for r in tool_calls)
    user_initiated = sum(1 for r in tool_calls if r.get("user_initiated"))
    self_initiated = len(tool_calls) - user_initiated

    total_tokens_in = sum(r.get("tokens_in", 0) for r in llm_calls)
    total_tokens_out = sum(r.get("tokens_out", 0) for r in llm_calls)

    # Action transition analysis
    transitions = Counter()
    for r in tool_calls:
        prev = r.get("prev_action", "none")
        curr = r.get("tool", "unknown")
        transitions[f"{prev} → {curr}"] += 1

    return {
        "total_tool_calls": len(tool_calls),
        "total_llm_calls": len(llm_calls),
        "total_user_messages": len(user_msgs),
        "user_initiated_calls": user_initiated,
        "self_initiated_calls": self_initiated,
        "top_tools": dict(tool_counter.most_common(10)),
        "top_transitions": dict(transitions.most_common(10)),
        "tokens": {"total_in": total_tokens_in, "total_out": total_tokens_out},
    }


def format_telegram_report(date_str, telemetry, actions):
    lines = [f"📊 <b>AgentGuard Daily Report — {date_str}</b>", ""]

    if telemetry:
        lines.append("🖥 <b>System Telemetry</b>")
        lines.append(f"Samples collected: {telemetry['samples']}")
        lines.append(f"CPU: avg {telemetry['cpu_pct']['avg']}% / max {telemetry['cpu_pct']['max']}%")
        lines.append(f"Memory: avg {telemetry['memory_pct']['avg']}% / max {telemetry['memory_pct']['max']}%")
        lines.append(f"Network conns: avg {telemetry['network_connections']['avg']} / max {telemetry['network_connections']['max']}")
        lines.append(f"Dest IP entropy: avg {telemetry['dest_ip_entropy']['avg']} / max {telemetry['dest_ip_entropy']['max']}")
        lines.append(f"Processes: avg {telemetry['process_count']['avg']} / max {telemetry['process_count']['max']}")
        lines.append("")
    else:
        lines.append("🖥 <i>No telemetry data collected</i>")
        lines.append("")

    if actions:
        lines.append("🤖 <b>Agent Actions</b>")
        lines.append(f"Tool calls: {actions['total_tool_calls']} ({actions['user_initiated_calls']} user / {actions['self_initiated_calls']} self)")
        lines.append(f"LLM calls: {actions['total_llm_calls']}")
        lines.append(f"User messages: {actions['total_user_messages']}")
        lines.append(f"Tokens: {actions['tokens']['total_in']:,} in / {actions['tokens']['total_out']:,} out")
        lines.append("")
        if actions["top_tools"]:
            lines.append("<b>Top tools:</b>")
            for tool, count in list(actions["top_tools"].items())[:5]:
                lines.append(f"  {tool}: {count}")
            lines.append("")
        if actions["top_transitions"]:
            lines.append("<b>Top transitions:</b>")
            for trans, count in list(actions["top_transitions"].items())[:5]:
                lines.append(f"  {trans}: {count}")
    else:
        lines.append("🤖 <i>No action data collected</i>")

    return "\n".join(lines)


def main():
    date_str = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d")
    if len(sys.argv) > 1:
        date_str = sys.argv[1]

    telemetry = summarize_telemetry(date_str)
    actions = summarize_actions(date_str)
    report_text = format_telegram_report(date_str, telemetry, actions)

    # Save report
    (DATA_DIR / "reports").mkdir(parents=True, exist_ok=True)
    report_path = DATA_DIR / "reports" / f"{date_str}.json"
    with open(report_path, "w") as f:
        json.dump({
            "date": date_str,
            "telemetry": telemetry,
            "actions": actions,
            "telegram_text": report_text,
        }, f, indent=2)

    # Print for piping
    print(report_text)


if __name__ == "__main__":
    main()
