#!/usr/bin/env python3
"""Workload: Heavy file operations — reads, writes, temp files, directory traversal."""
import os, time, random, tempfile, shutil, hashlib, json
from pathlib import Path
from datetime import datetime, timezone

WORK_DIR = Path(os.environ.get("WORKLOAD_DIR", "/tmp/agentguard_workload/fileops"))

def run():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    cycle = 0
    while True:
        cycle += 1
        action = random.choice(["write", "read", "copy", "delete", "traverse", "hash"])
        try:
            if action == "write":
                p = WORK_DIR / f"file_{random.randint(1,500)}.txt"
                p.write_text(f"data-{cycle}-" + "x" * random.randint(100, 50000))
            elif action == "read":
                files = list(WORK_DIR.glob("*.txt"))
                if files:
                    random.choice(files).read_text()
            elif action == "copy":
                files = list(WORK_DIR.glob("*.txt"))
                if files:
                    src = random.choice(files)
                    shutil.copy2(src, WORK_DIR / f"copy_{src.name}")
            elif action == "delete":
                files = list(WORK_DIR.glob("copy_*.txt"))
                if files:
                    random.choice(files).unlink()
            elif action == "traverse":
                for _ in os.walk(WORK_DIR):
                    pass
            elif action == "hash":
                files = list(WORK_DIR.glob("*.txt"))
                if files:
                    f = random.choice(files)
                    hashlib.sha256(f.read_bytes()).hexdigest()
        except Exception:
            pass
        time.sleep(random.uniform(0.5, 3))

if __name__ == "__main__":
    print("[Workload] fileops started")
    run()
