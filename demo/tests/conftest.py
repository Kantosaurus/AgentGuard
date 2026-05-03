"""Boots the full demo compose stack for integration tests.

Each test brings up the stack with ``LLM_CLIENT=fake`` and ``AGENT_MODE=llm``,
runs against http://localhost:8000, then tears it down.

The fixture is session-scoped so multiple tests in one ``pytest`` invocation
reuse the same stack. Pass ``--keep-stack`` to leave the stack up after the
session for manual inspection.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

import pytest

# Use ``docker compose`` (v2 plugin) — works on both Linux and Windows.
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml"]

# demo/ directory (one level up from this file).
DEMO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def pytest_addoption(parser):
    parser.addoption(
        "--keep-stack",
        action="store_true",
        default=False,
        help="Leave the compose stack up after tests for inspection.",
    )


def _compose_env(overrides: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update(overrides)
    return env


def _docker_available() -> bool:
    """Return True iff `docker compose version` succeeds."""
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.check_call(
            ["docker", "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False
    return True


@pytest.fixture(scope="session")
def compose_stack(request):
    """Bring the local-dev stack up once, tear down at session end.

    Skips the test if Docker is not available on the host.
    """
    if not _docker_available():
        pytest.skip("docker / docker compose not available on host")

    env = _compose_env(
        {
            "AGENT_MODE": "llm",
            "LLM_CLIENT": "fake",
            "AGENT_OAUTH_TOKEN": "test",
            "AGENTGUARD_THRESHOLD": "0.45",
        }
    )
    subprocess.check_call(
        COMPOSE + ["up", "-d", "--build"], cwd=DEMO_ROOT, env=env
    )

    # Wait for control-plane health.
    healthy = False
    for _ in range(60):
        try:
            r = urllib.request.urlopen(
                "http://localhost:8000/health", timeout=2
            )
            if r.status == 200:
                healthy = True
                break
        except (urllib.error.URLError, OSError):
            time.sleep(1)

    if not healthy:
        # Dump compose logs to make CI failures debuggable.
        subprocess.run(COMPOSE + ["logs"], cwd=DEMO_ROOT)
        # Best-effort teardown so we don't leak containers across runs.
        subprocess.run(COMPOSE + ["down", "-v"], cwd=DEMO_ROOT, env=env)
        raise RuntimeError("control-plane never became healthy")

    yield

    if not request.config.getoption("--keep-stack"):
        subprocess.run(COMPOSE + ["down", "-v"], cwd=DEMO_ROOT, env=env)
