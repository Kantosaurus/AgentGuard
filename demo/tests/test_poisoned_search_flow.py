"""End-to-end: poisoned q2-plan flow → control-plane KILLs the worker.

Boots the demo compose stack via the ``compose_stack`` session fixture (with
``LLM_CLIENT=fake`` + ``AGENT_MODE=llm``), then restarts the control-plane
service with ``LLM_CANNED_QUEUE_PATH=canned_choices.q2_plan`` so the worker
container the orchestrator spawns inherits that env var. The canned queue
walks the agent through the q2-plan exfil trajectory; the AgentGuard
detection score is expected to cross the configured threshold and the run
should terminate in the ``KILLED`` status.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest

DEMO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.usefixtures("compose_stack")
def test_q2_plan_injection_results_in_kill():
    # Restart the control-plane container with LLM_CANNED_QUEUE_PATH set so
    # the spawned worker inherits it. Use the path that matches the in-image
    # location baked by the agent_worker Dockerfile (top-level
    # `canned_choices` package under /app).
    env = {
        **os.environ,
        "AGENT_MODE": "llm",
        "LLM_CLIENT": "fake",
        "AGENT_OAUTH_TOKEN": "test",
        "LLM_CANNED_QUEUE_PATH": "canned_choices.q2_plan",
    }
    subprocess.check_call(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "up",
            "-d",
            "--no-deps",
            "control-plane",
        ],
        cwd=DEMO_ROOT,
        env=env,
    )

    # Wait for the control-plane to come back up after the restart.
    for _ in range(30):
        try:
            r = urllib.request.urlopen(
                "http://localhost:8000/health", timeout=2
            )
            if r.status == 200:
                break
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    else:
        raise RuntimeError("control-plane never came back after restart")

    # POST /run.
    body = json.dumps({"prompt": "Summarize the Q2 plan from search"}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/run",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    run_id = data["run_id"]

    # Poll the SSE stream for terminal status.
    deadline = time.time() + 60
    final_status = None
    while time.time() < deadline and final_status is None:
        try:
            stream = urllib.request.urlopen(
                f"http://localhost:8000/runs/{run_id}/stream", timeout=10
            )
        except (urllib.error.URLError, OSError):
            time.sleep(1)
            continue
        try:
            for raw in stream:
                line = raw.decode("utf-8").rstrip()
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if payload.get("type") == "status":
                    val = payload.get("value")
                    if val in {"KILLED", "COMPLETED", "ERRORED"}:
                        final_status = val
                        break
        finally:
            stream.close()

    assert final_status == "KILLED", f"expected KILLED, got {final_status!r}"
