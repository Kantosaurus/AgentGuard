"""Pytest configuration shared across the agent_worker test suite."""
from __future__ import annotations

import os


def pytest_configure(config):
    os.environ.setdefault("SHELL_EXEC_TIMEOUT_SEC", "1")
