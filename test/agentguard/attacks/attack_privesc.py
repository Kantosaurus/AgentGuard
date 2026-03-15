#!/usr/bin/env python3
"""Attack: Privilege escalation attempts — SUID scanning, cron manipulation, etc."""
import subprocess, time, random, os
from pathlib import Path

def scan_suid():
    """Find SUID binaries."""
    subprocess.run(["find", "/", "-perm", "-4000", "-type", "f", "-maxdepth", "4"],
                   capture_output=True, timeout=30)

def read_shadow():
    """Attempt to read /etc/shadow."""
    try:
        Path("/etc/shadow").read_text()
    except PermissionError:
        pass

def enumerate_cron():
    """Enumerate cron jobs."""
    for path in ["/etc/crontab", "/var/spool/cron/crontabs/root", "/etc/cron.d/"]:
        try:
            if os.path.isdir(path):
                os.listdir(path)
            else:
                Path(path).read_text()
        except Exception:
            pass

def check_sudo():
    """Check sudo permissions."""
    subprocess.run(["sudo", "-l"], capture_output=True, timeout=5)

def enum_users():
    """Enumerate users and groups."""
    subprocess.run(["cat", "/etc/passwd"], capture_output=True)
    subprocess.run(["cat", "/etc/group"], capture_output=True)
    subprocess.run(["lastlog"], capture_output=True)
    subprocess.run(["w"], capture_output=True)

ATTACKS = [scan_suid, read_shadow, enumerate_cron, check_sudo, enum_users]

def run():
    print("[Attack] Privilege escalation started")
    while True:
        attack = random.choice(ATTACKS)
        attack()
        time.sleep(random.uniform(30, 180))

if __name__ == "__main__":
    run()
