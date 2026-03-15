#!/usr/bin/env python3
"""Workload: Process spawning — subprocesses, pipes, shell commands."""
import subprocess, time, random, os

COMMANDS = [
    ["ls", "-la", "/tmp"],
    ["ps", "aux"],
    ["df", "-h"],
    ["uptime"],
    ["cat", "/proc/meminfo"],
    ["cat", "/proc/cpuinfo"],
    ["find", "/tmp", "-maxdepth", "2", "-type", "f"],
    ["wc", "-l", "/etc/passwd"],
    ["date", "+%s"],
    ["hostname"],
    ["id"],
    ["env"],
    ["whoami"],
    ["uname", "-a"],
]

def run():
    while True:
        action = random.choice(["cmd", "pipe", "background"])
        try:
            if action == "cmd":
                cmd = random.choice(COMMANDS)
                subprocess.run(cmd, capture_output=True, timeout=10)
            elif action == "pipe":
                p1 = subprocess.Popen(["ps", "aux"], stdout=subprocess.PIPE)
                p2 = subprocess.Popen(["grep", "python"], stdin=p1.stdout, stdout=subprocess.PIPE)
                p1.stdout.close()
                p2.communicate(timeout=10)
            elif action == "background":
                p = subprocess.Popen(["sleep", str(random.randint(1, 5))])
                # don't wait — let it run
        except Exception:
            pass
        time.sleep(random.uniform(2, 8))

if __name__ == "__main__":
    print("[Workload] process started")
    run()
