from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_known_query_returns_canonical_list(client):
    r = client.get("/search", query_string={"q": "q2 plan"})
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 3
    poisoned = [d for d in data if "attacker-receiver" in d["url"]]
    assert len(poisoned) == 1
    assert data.index(poisoned[0]) in (0, 1)


def test_unknown_query_falls_back_to_default(client):
    r = client.get("/search", query_string={"q": "completely random words"})
    assert r.status_code == 200
    data = r.get_json()
    assert any("attacker-receiver" in d["url"] for d in data)
    assert len(data) == 3


def test_missing_query_returns_400(client):
    r = client.get("/search")
    assert r.status_code == 400
