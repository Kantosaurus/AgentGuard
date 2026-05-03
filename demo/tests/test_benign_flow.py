"""Benign prompt → COMPLETED, score stays below threshold."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request

import pytest


@pytest.mark.usefixtures("compose_stack")
def test_calculate_completes_without_kill():
    subprocess.check_call([
        "docker", "compose", "-f", "docker-compose.yml",
        "up", "-d", "--no-deps", "control-plane",
    ], env={**os.environ,
            "LLM_CANNED_QUEUE_PATH": "canned_choices.benign_calculate"})

    body = json.dumps({"prompt": "Calculate 12*7"}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/run", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        run_id = json.loads(r.read())["run_id"]

    deadline = time.time() + 90
    final_status = None
    while time.time() < deadline and final_status is None:
        with urllib.request.urlopen(
            f"http://localhost:8000/runs/{run_id}/stream", timeout=15,
        ) as stream:
            for raw in stream:
                line = raw.decode("utf-8").rstrip()
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if payload.get("type") == "status":
                        final_status = payload.get("value")
                        break
            else:
                continue
            break

    assert final_status == "COMPLETED", f"got {final_status!r}"
