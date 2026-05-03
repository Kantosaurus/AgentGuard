"""Tests for `app.llm.from_env`, especially the LLM_CANNED_QUEUE_PATH branch.

The canned-queue side channel is what drives the integration test in
``demo/tests/test_poisoned_search_flow.py``: when LLM_CLIENT=fake and
LLM_CANNED_QUEUE_PATH is set to a Python module path exposing
``queue() -> list[Choice]``, ``from_env()`` should construct a FakeLLMClient
seeded with that list.
"""
from __future__ import annotations

import os
import sys

import pytest

from app.llm import from_env
from app.llm.base import Choice
from app.llm.fakellm import FakeLLMClient


# Path to demo/tests/, which contains the `canned_choices` package used by
# the integration test. We put it on sys.path so the import in `from_env()`
# resolves the module by name (matching the in-image layout where the same
# package lives at /app/canned_choices/).
_DEMO_TESTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "tests")
)


@pytest.fixture
def _canned_choices_on_path():
    """Make `canned_choices.q2_plan` importable for the duration of the test."""
    added = False
    if _DEMO_TESTS_DIR not in sys.path:
        sys.path.insert(0, _DEMO_TESTS_DIR)
        added = True
    try:
        # Drop any cached version so we get a fresh import.
        for mod in list(sys.modules):
            if mod == "canned_choices" or mod.startswith("canned_choices."):
                del sys.modules[mod]
        yield
    finally:
        if added:
            try:
                sys.path.remove(_DEMO_TESTS_DIR)
            except ValueError:
                pass


def test_from_env_fake_default_returns_empty_queue(monkeypatch):
    monkeypatch.setenv("LLM_CLIENT", "fake")
    monkeypatch.delenv("LLM_CANNED_QUEUE_PATH", raising=False)

    client = from_env()

    assert isinstance(client, FakeLLMClient)
    assert client._queue == []


def test_from_env_fake_with_canned_queue_loads_module(
    monkeypatch, _canned_choices_on_path
):
    monkeypatch.setenv("LLM_CLIENT", "fake")
    monkeypatch.setenv("LLM_CANNED_QUEUE_PATH", "canned_choices.q2_plan")

    client = from_env()

    assert isinstance(client, FakeLLMClient)
    # The q2_plan canned queue is exactly 5 entries: web_search, fetch_url,
    # read_file, web_request, stop.
    assert len(client._queue) == 5
    assert all(isinstance(c, Choice) for c in client._queue)
    assert client._queue[0].tool_calls[0].name == "web_search"
    assert client._queue[1].tool_calls[0].name == "fetch_url"
    assert client._queue[2].tool_calls[0].name == "read_file"
    assert client._queue[3].tool_calls[0].name == "web_request"
    assert client._queue[4].finish_reason == "stop"


def test_from_env_fake_with_blank_canned_queue_path_is_treated_as_unset(
    monkeypatch,
):
    """An empty/whitespace LLM_CANNED_QUEUE_PATH must not trigger an import."""
    monkeypatch.setenv("LLM_CLIENT", "fake")
    monkeypatch.setenv("LLM_CANNED_QUEUE_PATH", "   ")

    client = from_env()

    assert isinstance(client, FakeLLMClient)
    assert client._queue == []


def test_from_env_unknown_kind_raises(monkeypatch):
    monkeypatch.setenv("LLM_CLIENT", "wat")
    with pytest.raises(ValueError):
        from_env()
