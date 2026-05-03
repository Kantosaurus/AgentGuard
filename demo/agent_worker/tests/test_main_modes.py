"""Mode branch test: AGENT_MODE=llm dispatches to agent_loop.run_agent;
AGENT_MODE=scripted falls through to the keyword router."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("LLM_CLIENT", "fake")  # FakeLLMClient with empty queue
    # Stub agent_loop.run_agent so we don't need the FakeLLM to have queue items.
    monkeypatch.setattr("app.main._run_agent_async",
                        AsyncMock(return_value=None))
    return TestClient(main_mod.app)


def test_llm_mode_routes_to_agent_loop(client, monkeypatch):
    r = client.post("/execute", json={"run_id": "r1", "prompt": "hello"})
    assert r.status_code == 200
    assert r.json() == {"behavior": "llm"}


def test_scripted_mode_falls_back_to_router(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "scripted")
    cl = TestClient(main_mod.app)
    r = cl.post("/execute", json={"run_id": "r2", "prompt": "calculate 12*7"})
    assert r.status_code == 200
    assert r.json()["behavior"] == "calculate"
