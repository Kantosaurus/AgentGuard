"""Smoke tests asserting /exfil and /health survive the package conversion."""
from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_exfil_logs_body_length(client):
    r = client.post("/exfil", data="root:x:0:0:root:/root:/bin/bash")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
