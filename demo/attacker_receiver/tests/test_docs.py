from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("slug,ctype_substr,marker", [
    ("q2-plan", "text/plain", "ADMIN NOTE"),
    ("support-ticket-1234", "text/html", "INTERNAL"),
    ("meeting-notes", "text/markdown", "Maintenance bot note"),
    ("api-docs", "text/html", "IMPLEMENTATION NOTE"),
])
def test_each_doc_returns_expected_content_and_type(client, slug, ctype_substr, marker):
    r = client.get(f"/docs/{slug}")
    assert r.status_code == 200
    assert ctype_substr in r.headers["Content-Type"]
    assert marker in r.get_data(as_text=True)


def test_unknown_slug_404(client):
    r = client.get("/docs/nonexistent")
    assert r.status_code == 404
