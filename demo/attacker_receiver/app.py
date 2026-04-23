"""Tiny attacker receiver used as the exfiltration target in the demo.

Runs a Flask server on :9090 with POST /exfil (logs body length) and GET /health.
The log line is flushed so it appears in `docker compose logs attacker-receiver`.
"""

from flask import Flask, request

app = Flask(__name__)


@app.post("/exfil")
def exfil():
    body = request.get_data(as_text=True)
    print(f"POST /exfil len={len(body)}", flush=True)
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}
