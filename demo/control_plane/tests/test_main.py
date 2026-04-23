"""Lightweight FastAPI smoke tests that do NOT require the model to load.

/health must respond 200 and tell us whether the RunManager came up. Uses the
standard FastAPI TestClient so no real docker daemon or model load is needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint():
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "run_manager_ready" in body
