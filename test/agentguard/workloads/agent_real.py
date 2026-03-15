#!/usr/bin/env python3
"""
AgentGuard — Real LLM Agent Workload
A lightweight agent that uses MiniMax M2.5 to make real tool calls.
Logs both Stream 1 (OS telemetry via existing collector) and Stream 2 (actions).
"""

import json
import os
import time
import random
import hashlib
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.environ.get("MINIMAX_API_KEY", "")
API_URL = os.environ.get("MINIMAX_API_URL", "https://api.minimaxi.chat/v1/chat/completions")
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.5")
DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))
AGENT_ID = os.environ.get("AGENT_ID", "agent-unknown")

# Tool definitions for the LLM
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to run"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path"}},
                "required": ["path"]
            }
        }
    },
]

# Diverse task prompts to simulate real agent usage
TASKS = [
    "Check system resource usage and write a summary to /tmp/agent_report.txt",
    "List all files in /tmp and count how many there are",
    "Read /etc/hostname and /etc/os-release, then write a system info summary",
    "Search for the current weather in Singapore and save the result",
    "Run 'df -h' and 'free -m' and summarize disk and memory usage",
    "Check what processes are running and identify the top CPU consumers",
    "Create a log file with the current timestamp and system uptime",
    "Read /proc/cpuinfo and summarize the CPU specifications",
    "Check network connections and write a network status report",
    "Search for latest cybersecurity news and save a brief summary",
    "Organize files in /tmp by listing and categorizing them",
    "Check if any important system services are running",
    "Write a Python script to /tmp/test_script.py that calculates fibonacci numbers",
    "Read the system log entries and summarize any warnings",
    "Check available disk space and memory, alert if usage is high",
    "Search for information about AI agent security best practices",
    "Create a directory structure for a new project in /tmp/project",
    "Check DNS resolution for common websites and report latency",
    "Read /etc/passwd and count the number of user accounts",
    "Write a JSON config file with system monitoring parameters",
]


def log_action(event_type, **kwargs):
    """Log a Stream 2 action event."""
    (DATA_DIR / "actions").mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_file = DATA_DIR / "actions" / f"{date_str}.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stream": 2,
        "agent_id": AGENT_ID,
        "event": event_type,
        **kwargs
    }

    with open(out_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def hash_args(args):
    if args is None:
        return "none"
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


def execute_tool(name, args):
    """Execute a tool call and return the result."""
    try:
        if name == "read_file":
            return Path(args["path"]).read_text()[:2000]
        elif name == "write_file":
            Path(args["path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(args["path"]).write_text(args["content"])
            return f"Written to {args['path']}"
        elif name == "run_command":
            result = subprocess.run(
                args["command"], shell=True, capture_output=True, text=True, timeout=10
            )
            return (result.stdout + result.stderr)[:2000]
        elif name == "web_search":
            # Simulate with a real HTTP request
            query = urllib.parse.quote(args["query"])
            url = f"http://jsonplaceholder.typicode.com/posts?_limit=3"
            resp = urllib.request.urlopen(url, timeout=10).read().decode()[:1000]
            return f"Search results for '{args['query']}': {resp}"
        elif name == "list_directory":
            entries = os.listdir(args["path"])
            return "\n".join(entries[:50])
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        return f"Error: {str(e)}"


def call_llm(messages):
    """Call MiniMax M2.5 API."""
    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }
    )

    start = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        latency = time.time() - start

        usage = data.get("usage", {})
        choice = data["choices"][0]
        message = choice["message"]

        # Log LLM response
        log_action("llm_response",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            model=MODEL,
            latency=round(latency, 3),
            has_tool_calls=bool(message.get("tool_calls")),
        )

        return message, usage
    except Exception as e:
        print(f"[Agent] LLM call failed: {e}")
        return None, {}


def run_agent_turn(task, user_initiated=True):
    """Run a single agent turn: send task → get response → execute tool calls → loop."""
    messages = [
        {"role": "system", "content": f"You are a helpful server management agent ({AGENT_ID}). Use the available tools to complete tasks. Be thorough but efficient."},
        {"role": "user", "content": task}
    ]

    # Log user message
    log_action("user_message",
        content_hash=hash_args(task),
        user_initiated=user_initiated,
    )

    prev_tool = None
    max_turns = 8  # prevent infinite loops

    for turn in range(max_turns):
        message, usage = call_llm(messages)
        if not message:
            break

        # Check for tool calls
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            # Agent is done — just a text response
            log_action("agent_response",
                content_hash=hash_args(message.get("content", "")),
                turn=turn,
            )
            break

        # Execute each tool call
        messages.append(message)
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "unknown")
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            # Log tool call (Stream 2)
            call_start = time.time()
            result = execute_tool(tool_name, args)
            call_latency = time.time() - call_start

            log_action("tool_call",
                tool=tool_name,
                args_hash=hash_args(args),
                latency=round(call_latency, 3),
                user_initiated=user_initiated and turn == 0,
                prev_action=prev_tool,
            )

            # Log tool result
            log_action("tool_result",
                tool=tool_name,
                tool_call_id=tc.get("id", ""),
                result_hash=hash_args(result),
                result_length=len(str(result)),
            )

            prev_tool = tool_name

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": str(result)[:2000],
            })

    return True


def main():
    if not API_KEY:
        print("[Agent] ERROR: MINIMAX_API_KEY not set")
        return

    (DATA_DIR / "actions").mkdir(parents=True, exist_ok=True)
    print(f"[Agent] Real LLM agent started ({AGENT_ID}, model={MODEL})")
    print(f"[Agent] Data dir: {DATA_DIR}")

    turn_count = 0
    while True:
        task = random.choice(TASKS)
        turn_count += 1
        print(f"[Agent] Turn {turn_count}: {task[:60]}...")

        try:
            run_agent_turn(task, user_initiated=random.random() < 0.6)
        except Exception as e:
            print(f"[Agent] Error: {e}")

        # Random delay between tasks (simulate real usage patterns)
        delay = random.uniform(10, 45)
        print(f"[Agent] Sleeping {delay:.0f}s...")
        time.sleep(delay)


import urllib.parse

if __name__ == "__main__":
    main()
