#!/usr/bin/env python3
"""
AgentGuard — Stream 1: System Telemetry Collector
Collects CPU, memory, process, I/O, network, and syscall metrics at configurable intervals.
Outputs JSONL to a daily log file.
"""

import json
import os
import time
import subprocess
import math
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))
INTERVAL = int(os.environ.get("AGENTGUARD_TELEMETRY_INTERVAL", "5"))  # seconds


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "telemetry").mkdir(exist_ok=True)
    (DATA_DIR / "actions").mkdir(exist_ok=True)
    (DATA_DIR / "reports").mkdir(exist_ok=True)


def get_cpu_memory():
    cpu = {}
    mem = {}
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        fields = [int(x) for x in line.strip().split()[1:]]
        cpu["total_jiffies"] = sum(fields)
        cpu["idle_jiffies"] = fields[3] + fields[4]
    except Exception as e:
        cpu["error"] = str(e)

    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
        mem["total_kb"] = meminfo.get("MemTotal", 0)
        mem["available_kb"] = meminfo.get("MemAvailable", 0)
        mem["used_kb"] = mem["total_kb"] - mem["available_kb"]
        mem["usage_pct"] = round(mem["used_kb"] / max(mem["total_kb"], 1) * 100, 2)
    except Exception as e:
        mem["error"] = str(e)

    return cpu, mem


def get_process_info():
    try:
        return {"count": len([p for p in os.listdir("/proc") if p.isdigit()])}
    except Exception as e:
        return {"error": str(e)}


def get_file_io():
    try:
        with open("/proc/diskstats") as f:
            lines = f.readlines()
        reads = writes = 0
        for line in lines:
            parts = line.split()
            if len(parts) >= 14:
                reads += int(parts[5])
                writes += int(parts[9])
        return {"sectors_read": reads, "sectors_written": writes}
    except Exception as e:
        return {"error": str(e)}


def get_network_info():
    try:
        result = subprocess.run(["ss", "-tunH"], capture_output=True, text=True, timeout=5)
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        dest_ips = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 5:
                dest_ips.append(parts[4].rsplit(":", 1)[0])

        entropy = 0.0
        if dest_ips:
            counter = Counter(dest_ips)
            total = len(dest_ips)
            for count in counter.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log2(p)

        return {
            "connection_count": len(lines),
            "unique_dest_ips": len(set(dest_ips)),
            "dest_ip_entropy": round(entropy, 4)
        }
    except Exception as e:
        return {"error": str(e)}


def get_syscall_freq():
    try:
        syscall_ids = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/syscall") as f:
                    data = f.read().strip()
                    if data and data != "running":
                        sc_num = data.split()[0]
                        if sc_num.isdigit():
                            syscall_ids.append(int(sc_num))
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
        counter = Counter(syscall_ids)
        return {"sample_count": len(syscall_ids), "unique_syscalls": len(counter), "top_5": dict(counter.most_common(5))}
    except Exception as e:
        return {"error": str(e)}


_prev = {}

def compute_rates(cpu, io):
    rates = {}
    if "total_jiffies" in cpu and "cpu" in _prev:
        d_total = cpu["total_jiffies"] - _prev["cpu"]["total_jiffies"]
        d_idle = cpu["idle_jiffies"] - _prev["cpu"]["idle_jiffies"]
        if d_total > 0:
            rates["cpu_usage_pct"] = round((1 - d_idle / d_total) * 100, 2)
    if "sectors_read" in io and "io" in _prev:
        rates["read_sectors_per_sec"] = round((io["sectors_read"] - _prev["io"]["sectors_read"]) / INTERVAL, 2)
        rates["write_sectors_per_sec"] = round((io["sectors_written"] - _prev["io"]["sectors_written"]) / INTERVAL, 2)
    _prev["cpu"] = cpu
    _prev["io"] = io
    return rates


def collect_sample():
    ts = datetime.now(timezone.utc).isoformat()
    cpu, mem = get_cpu_memory()
    procs = get_process_info()
    io = get_file_io()
    net = get_network_info()
    syscalls = get_syscall_freq()
    rates = compute_rates(cpu, io)

    return {
        "timestamp": ts,
        "stream": 1,
        "cpu": {**cpu, **{k: v for k, v in rates.items() if "cpu" in k}},
        "memory": mem,
        "processes": procs,
        "file_io": {**io, **{k: v for k, v in rates.items() if "sector" in k}},
        "network": net,
        "syscalls": syscalls,
    }


def main():
    ensure_data_dir()
    print(f"[AgentGuard] Telemetry collector started (interval={INTERVAL}s)")
    while True:
        try:
            sample = collect_sample()
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            out_file = DATA_DIR / "telemetry" / f"{date_str}.jsonl"
            with open(out_file, "a") as f:
                f.write(json.dumps(sample) + "\n")
        except Exception as e:
            print(f"[AgentGuard] Telemetry error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
