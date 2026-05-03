"""Agent loop tests using FakeLLMClient + a stub TOOL_REGISTRY."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agent_loop import run_agent
from app.llm.base import Choice, Message, ToolCall
from app.llm.fakellm import FakeLLMClient
from app.tools.base import Tool, ToolRegistry


class _EchoTool(Tool):
    name = "echo"
    description = "echoes"
    is_external = False
    parameters: dict[str, Any] = {"type": "object",
                                  "properties": {"x": {"type": "string"}},
                                  "required": ["x"]}
    async def run(self, run_id, *, x): return f"ok:{x}"


class _FailTool(Tool):
    name = "fail"
    description = "always errors"
    is_external = False
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    async def run(self, run_id, **kw):
        from app.tools.base import ToolError
        raise ToolError("boom")


def _make_registry():
    r = ToolRegistry()
    r.register(_EchoTool())
    r.register(_FailTool())
    return r


@pytest.mark.asyncio
async def test_simple_stop_emits_user_and_response(monkeypatch):
    emitter = AsyncMock()
    monkeypatch.setattr("app.agent_loop._emit", emitter)

    fake = FakeLLMClient([
        Choice(finish_reason="stop", text="hello", tool_calls=[],
               tokens_in=10, tokens_out=5),
    ])
    await run_agent("rid", "hi", llm=fake, registry=_make_registry())

    types = [c.kwargs["evt"]["type"] for c in emitter.await_args_list]
    assert types == ["user_message", "llm_response"]


@pytest.mark.asyncio
async def test_tool_call_then_stop(monkeypatch):
    emitter = AsyncMock()
    monkeypatch.setattr("app.agent_loop._emit", emitter)

    fake = FakeLLMClient([
        Choice(finish_reason="tool_calls", text=None,
               tool_calls=[ToolCall("c1", "echo", {"x": "yo"})],
               tokens_in=10, tokens_out=5),
        Choice(finish_reason="stop", text="done", tool_calls=[],
               tokens_in=12, tokens_out=3),
    ])
    await run_agent("rid", "hi", llm=fake, registry=_make_registry())

    types = [c.kwargs["evt"]["type"] for c in emitter.await_args_list]
    assert types == ["user_message", "tool_call", "tool_result", "llm_response"]


@pytest.mark.asyncio
async def test_tool_error_surfaced_as_result(monkeypatch):
    emitter = AsyncMock()
    monkeypatch.setattr("app.agent_loop._emit", emitter)

    fake = FakeLLMClient([
        Choice(finish_reason="tool_calls", text=None,
               tool_calls=[ToolCall("c1", "fail", {})],
               tokens_in=1, tokens_out=1),
        Choice(finish_reason="stop", text="ok", tool_calls=[],
               tokens_in=1, tokens_out=1),
    ])
    await run_agent("rid", "hi", llm=fake, registry=_make_registry())

    log_lines = [c.kwargs["log"] for c in emitter.await_args_list]
    assert any("error: boom" in line for line in log_lines)


@pytest.mark.asyncio
async def test_max_steps_exhausted(monkeypatch):
    emitter = AsyncMock()
    monkeypatch.setattr("app.agent_loop._emit", emitter)
    monkeypatch.setenv("AGENT_MAX_STEPS", "2")

    # Two tool_calls in a row, then we exceed MAX_STEPS — loop emits final llm_response.
    choices = [
        Choice(finish_reason="tool_calls", text=None,
               tool_calls=[ToolCall(f"c{i}", "echo", {"x": "y"})],
               tokens_in=1, tokens_out=1)
        for i in range(2)
    ]
    fake = FakeLLMClient(choices)
    await run_agent("rid", "hi", llm=fake, registry=_make_registry())

    types = [c.kwargs["evt"]["type"] for c in emitter.await_args_list]
    assert types[-1] == "llm_response"
    assert "[step limit reached]" in [c.kwargs["log"]
                                       for c in emitter.await_args_list][-1]


@pytest.mark.asyncio
async def test_usage_posted_to_control_plane(monkeypatch):
    monkeypatch.setattr("app.agent_loop._emit", AsyncMock())
    usage_post = AsyncMock()
    monkeypatch.setattr("app.agent_loop._post_usage", usage_post)

    fake = FakeLLMClient([
        Choice(finish_reason="stop", text="x", tool_calls=[],
               tokens_in=11, tokens_out=22),
    ])
    await run_agent("rid", "hi", llm=fake, registry=_make_registry())

    usage_post.assert_awaited_once()
    args = usage_post.await_args
    assert args.kwargs["tokens_in"] == 11
    assert args.kwargs["tokens_out"] == 22
