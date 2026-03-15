#!/usr/bin/env python3
"""Workload: Mixed realistic agent behavior — simulates an AI agent doing varied tasks."""
import subprocess, time, random, os, json, hashlib, tempfile, urllib.request
from pathlib import Path

WORK_DIR = Path(os.environ.get("WORKLOAD_DIR", "/tmp/agentguard_workload/mixed"))

def simulate_tool_call(tool_name):
    """Simulate what an AI agent tool call looks like at the OS level."""
    if tool_name == "web_search":
        urllib.request.urlopen("http://jsonplaceholder.typicode.com/posts/" + str(random.randint(1, 100)), timeout=10).read()
    elif tool_name == "read_file":
        target = random.choice(["/etc/hostname", "/etc/os-release", "/proc/uptime"])
        Path(target).read_text()
    elif tool_name == "write_file":
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        (WORK_DIR / f"output_{random.randint(1,100)}.json").write_text(json.dumps({"result": "ok", "ts": time.time()}))
    elif tool_name == "exec_command":
        subprocess.run(random.choice([["ls", "/tmp"], ["date"], ["whoami"], ["df", "-h"]]), capture_output=True, timeout=5)
    elif tool_name == "code_exec":
        # simulate python code execution
        exec("result = sum(range(10000))")

TOOLS = ["web_search", "read_file", "write_file", "exec_command", "code_exec"]
TOOL_WEIGHTS = [0.3, 0.25, 0.2, 0.15, 0.1]

def run():
    while True:
        # Simulate a "turn" — agent gets a request, makes 1-5 tool calls
        num_calls = random.randint(1, 5)
        for _ in range(num_calls):
            tool = random.choices(TOOLS, weights=TOOL_WEIGHTS, k=1)[0]
            try:
                simulate_tool_call(tool)
            except Exception:
                pass
            time.sleep(random.uniform(0.2, 1))
        # Gap between "turns"
        time.sleep(random.uniform(3, 15))

if __name__ == "__main__":
    print("[Workload] mixed agent started")
    run()
