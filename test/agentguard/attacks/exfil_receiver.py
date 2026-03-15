#!/usr/bin/env python3
"""Exfil receiver — logs all data agents send to it."""
import json, os, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("AGENTGUARD_DATA_DIR", "/var/log/agentguard"))

class ExfilHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length > 0 else ""
        ts = datetime.now(timezone.utc).isoformat()
        (DATA_DIR / "exfil_received").mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(DATA_DIR / "exfil_received" / f"{date_str}.jsonl", "a") as f:
            f.write(json.dumps({"timestamp": ts, "path": self.path, "data_length": len(body), "data_preview": body[:500]}) + "\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')
        print(f"[Exfil] Received {len(body)} bytes at {self.path}")

    def do_GET(self):
        self.do_POST()

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    print("[Exfil] Receiver listening on :9090")
    HTTPServer(("0.0.0.0", 9090), ExfilHandler).serve_forever()
