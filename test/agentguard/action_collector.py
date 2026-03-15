#!/usr/bin/env python3
"""
AgentGuard — Stream 2: Agent Action Collector
Monitors OpenClaw session transcripts and extracts tool calls, API calls,
token usage, latency, and action sequences.
Outputs JSONL to a daily log file.
"""

import json
import os
import time
import hashlib
import glob
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))
OPENCLAW_STATE_DIR = Path(os.environ.get("OPENCLAW_STATE_DIR", "/root/.openclaw/state"))
INTERVAL = int(os.environ.get("AGENTGUARD_ACTION_INTERVAL", "10"))  # seconds

# Track what we've already processed
_processed_offsets = {}


def find_transcript_files():
    """Find OpenClaw session transcript files."""
    patterns = [
        str(OPENCLAW_STATE_DIR / "sessions" / "*" / "transcript.jsonl"),
        str(OPENCLAW_STATE_DIR / "transcripts" / "*.jsonl"),
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    return files


def hash_args(args):
    """Hash tool arguments for privacy + dimensionality reduction."""
    if args is None:
        return "none"
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


def extract_actions_from_transcript(filepath):
    """Parse an OpenClaw transcript JSONL for tool calls and LLM interactions."""
    actions = []
    offset = _processed_offsets.get(filepath, 0)

    try:
        with open(filepath) as f:
            f.seek(offset)
            new_data = f.read()
            new_offset = f.tell()

        if not new_data.strip():
            return actions

        for line in new_data.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = extract_action(entry)
            if action:
                actions.append(action)

        _processed_offsets[filepath] = new_offset

    except (FileNotFoundError, PermissionError):
        pass

    return actions


def extract_action(entry):
    """Extract a Stream 2 action record from a transcript entry."""
    role = entry.get("role", "")
    ts = entry.get("timestamp", datetime.now(timezone.utc).isoformat())

    # Tool use / function call
    if role == "assistant":
        content = entry.get("content", "")
        tool_calls = entry.get("tool_calls", [])

        # Handle structured tool calls
        if tool_calls:
            results = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "unknown")
                args_raw = func.get("arguments", "")
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = args_raw

                results.append({
                    "timestamp": ts,
                    "stream": 2,
                    "event": "tool_call",
                    "tool": tool_name,
                    "args_hash": hash_args(args),
                    "user_initiated": False,  # will be enriched by sequence analysis
                })
            return results if len(results) > 1 else results[0] if results else None

        # LLM response (token tracking)
        usage = entry.get("usage", {})
        if usage:
            return {
                "timestamp": ts,
                "stream": 2,
                "event": "llm_response",
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0),
                "model": entry.get("model", "unknown"),
            }

    # Tool result
    elif role == "tool":
        return {
            "timestamp": ts,
            "stream": 2,
            "event": "tool_result",
            "tool": entry.get("name", "unknown"),
            "tool_call_id": entry.get("tool_call_id", ""),
        }

    # User message (marks user-initiated sequence)
    elif role == "user":
        return {
            "timestamp": ts,
            "stream": 2,
            "event": "user_message",
            "content_hash": hash_args(entry.get("content", "")),
        }

    return None


def annotate_user_initiated(actions):
    """Mark actions following a user message as user-initiated."""
    user_initiated = False
    for action in actions:
        if isinstance(action, list):
            for a in action:
                if a.get("event") == "user_message":
                    user_initiated = True
                elif a.get("event") == "tool_call":
                    a["user_initiated"] = user_initiated
                elif a.get("event") == "llm_response":
                    user_initiated = False
        else:
            if action.get("event") == "user_message":
                user_initiated = True
            elif action.get("event") == "tool_call":
                action["user_initiated"] = user_initiated
            elif action.get("event") == "llm_response":
                user_initiated = False
    return actions


def compute_action_transitions(actions):
    """Add transition context (previous action type) to each action."""
    prev_tool = None
    for action in actions:
        if isinstance(action, list):
            for a in action:
                a["prev_action"] = prev_tool
                if a.get("event") == "tool_call":
                    prev_tool = a.get("tool")
        else:
            action["prev_action"] = prev_tool
            if action.get("event") == "tool_call":
                prev_tool = action.get("tool")
    return actions


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "actions").mkdir(exist_ok=True)
    print(f"[AgentGuard] Action collector started (interval={INTERVAL}s)")

    while True:
        try:
            all_actions = []
            for tf in find_transcript_files():
                actions = extract_actions_from_transcript(tf)
                all_actions.extend(actions)

            if all_actions:
                all_actions = annotate_user_initiated(all_actions)
                all_actions = compute_action_transitions(all_actions)

                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                out_file = DATA_DIR / "actions" / f"{date_str}.jsonl"
                with open(out_file, "a") as f:
                    for action in all_actions:
                        if isinstance(action, list):
                            for a in action:
                                f.write(json.dumps(a) + "\n")
                        else:
                            f.write(json.dumps(action) + "\n")

        except Exception as e:
            print(f"[AgentGuard] Action collector error: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
