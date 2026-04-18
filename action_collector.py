#!/usr/bin/env python3
"""
AgentGuard — Server-Side Agent Action Collector
Deploy this on your SSH server alongside your agent runtime.

This script provides two things:
1. A hook/wrapper that intercepts OpenClaw (or any agent) events and writes
   them to /var/log/agentguard/actions/YYYY-MM-DD.jsonl
2. A simple stdin-based prompt executor you can call from the dashboard.

Usage (prompt executor, called by dashboard):
    echo "your prompt here" | python3 action_collector.py --mode exec

Usage (standalone event logger — integrate into your agent loop):
    from action_collector import log_action_event
    log_action_event(event_type="tool_call", tool="read_file", tokens_in=100, ...)

Requires: no extra dependencies beyond stdlib
"""

import argparse
import datetime
import json
import os
import sys
import subprocess
from pathlib import Path

LOG_ROOT = Path("/var/log/agentguard/actions")


def log_action_event(
    event_type: str,
    tool: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency: float = 0.0,
    source: str = "user",
    user_initiated: bool = True,
    has_tool_calls: bool = False,
    extra: dict = None,
):
    """
    Write one action event to today's JSONL log.
    Call this from within your agent code to instrument every tool call,
    LLM response, and user message.
    """
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    today   = datetime.date.today().isoformat()
    logfile = LOG_ROOT / f"{today}.jsonl"

    record = {
        "timestamp":     datetime.datetime.utcnow().isoformat(),
        "event":         event_type,           # "user_message" | "llm_response" | "tool_call" | "tool_result"
        "tool":          tool,
        "tokens_in":     tokens_in,
        "tokens_out":    tokens_out,
        "latency":       latency,
        "source":        source,               # "user" | "attacker-<id>" | "internal"
        "user_initiated": user_initiated,
        "has_tool_calls": has_tool_calls,
    }
    if extra:
        record.update(extra)

    with open(logfile, "a") as f:
        f.write(json.dumps(record) + "\n")


# ── Prompt executor (called by dashboard via SSH) ─────────────────────────────

def exec_prompt(prompt_text: str):
    """
    Execute a user prompt through the local agent.
    EDIT THIS FUNCTION to match your actual agent CLI / API.

    Current placeholder: just echoes the prompt and logs the event.
    Replace the subprocess call with your actual agent invocation.
    """
    ts_start = datetime.datetime.utcnow()

    # Log the incoming user message
    log_action_event(
        event_type="user_message",
        source="user",
        user_initiated=True,
        extra={"prompt_preview": prompt_text[:200]},
    )

    # ── REPLACE THIS with your actual agent call ─────────────────────────────
    # Example for OpenClaw:
    #   result = subprocess.run(
    #       ["openclaw", "run", "--prompt", prompt_text],
    #       capture_output=True, text=True, timeout=60
    #   )
    #   output = result.stdout
    # ─────────────────────────────────────────────────────────────────────────
    # Placeholder — just echoes back
    output = f"[PLACEHOLDER] Agent received: {prompt_text}"
    print(output)

    latency = (datetime.datetime.utcnow() - ts_start).total_seconds()

    # Log the agent response
    log_action_event(
        event_type="agent_response",
        tokens_out=len(output.split()),
        latency=round(latency, 3),
        source="agent",
    )


# ── OpenClaw integration hooks (optional) ─────────────────────────────────────

class AgentGuardOpenClawHook:
    """
    Attach this hook to an OpenClaw session to automatically log all events.

    Usage:
        from action_collector import AgentGuardOpenClawHook
        hook = AgentGuardOpenClawHook()
        # attach to your OpenClaw session event callbacks
    """

    def on_tool_call(self, tool_name: str, args: dict, session_id: str = ""):
        log_action_event(
            event_type="tool_call",
            tool=tool_name,
            source="agent",
            has_tool_calls=True,
            extra={"session_id": session_id},
        )

    def on_tool_result(self, tool_name: str, result: str, latency: float, session_id: str = ""):
        log_action_event(
            event_type="tool_result",
            tool=tool_name,
            latency=latency,
            source="agent",
            extra={"session_id": session_id, "result_preview": str(result)[:200]},
        )

    def on_llm_response(self, tokens_in: int, tokens_out: int, model: str = ""):
        log_action_event(
            event_type="llm_response",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            source="internal",
            extra={"model": model},
        )

    def on_user_message(self, message: str):
        log_action_event(
            event_type="user_message",
            source="user",
            user_initiated=True,
            extra={"preview": message[:200]},
        )


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AgentGuard Action Collector")
    parser.add_argument("--mode", choices=["exec", "log"], default="exec",
                        help="exec: read prompt from stdin and run agent; log: write a test event")
    args = parser.parse_args()

    if args.mode == "exec":
        prompt = sys.stdin.read().strip()
        if prompt:
            exec_prompt(prompt)
        else:
            print("[AgentGuard] No prompt received on stdin.", file=sys.stderr)
            sys.exit(1)

    elif args.mode == "log":
        # Write a test heartbeat event
        log_action_event(
            event_type="agent_response",
            source="heartbeat",
            tokens_out=0,
            extra={"note": "manual test event"},
        )
        print(f"[AgentGuard] Test event written to {LOG_ROOT}/")


if __name__ == "__main__":
    main()
