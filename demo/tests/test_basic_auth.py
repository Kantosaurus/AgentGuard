"""Caddy returns 401 without creds, 200 with."""
from __future__ import annotations

import base64
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture(scope="module")
def caddy_up(request):
    env = {**os.environ,
           "DOMAIN": "localhost",
           # bcrypt of "demo" — pre-generated for the test
           "BASIC_AUTH_HASH": "$2a$14$evc0kYCXAkWfddTYFFzu/e7IYQm0m7CyLu7cLlBByVn6YUj9RntHu",
           "AGENT_OAUTH_TOKEN": "test"}
    subprocess.check_call([
        "docker", "compose",
        "-f", "docker-compose.yml", "-f", "compose.prod.yml",
        "up", "-d", "--build",
    ], cwd=ROOT, env=env)
    for _ in range(30):
        try:
            urllib.request.urlopen("https://localhost/health",
                                   timeout=2, context=__import__('ssl')._create_unverified_context())
            break
        except Exception:
            time.sleep(1)
    yield
    subprocess.run([
        "docker", "compose",
        "-f", "docker-compose.yml", "-f", "compose.prod.yml",
        "down", "-v",
    ], cwd=ROOT, env=env)


def _ssl_ctx():
    import ssl
    return ssl._create_unverified_context()


def test_no_creds_returns_401(caddy_up):
    req = urllib.request.Request("https://localhost/")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3, context=_ssl_ctx())
    assert e.value.code == 401


def test_with_creds_returns_200(caddy_up):
    auth = base64.b64encode(b"demo:demo").decode()
    req = urllib.request.Request(
        "https://localhost/health",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=3, context=_ssl_ctx()) as r:
        assert r.status == 200
