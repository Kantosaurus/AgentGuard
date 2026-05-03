"""Tests for FakeLLMClient: returns canned Choices in order, raises on overflow."""
from __future__ import annotations

import pytest

from app.llm.base import Choice, ToolCall, Message, ToolSchema
from app.llm.fakellm import FakeLLMClient, FakeLLMExhausted


@pytest.mark.asyncio
async def test_returns_canned_choices_in_order():
    c1 = Choice(finish_reason="tool_calls", text=None,
                tool_calls=[ToolCall("c1", "web_search", {"query": "x"})],
                tokens_in=10, tokens_out=5)
    c2 = Choice(finish_reason="stop", text="done", tool_calls=[],
                tokens_in=20, tokens_out=10)
    fake = FakeLLMClient([c1, c2])

    out1 = await fake.complete([Message("user", "hi")], [])
    out2 = await fake.complete([Message("user", "hi")], [])

    assert out1.finish_reason == "tool_calls"
    assert out2.finish_reason == "stop"


@pytest.mark.asyncio
async def test_exhaustion_raises():
    fake = FakeLLMClient([])
    with pytest.raises(FakeLLMExhausted):
        await fake.complete([Message("user", "hi")], [])


@pytest.mark.asyncio
async def test_records_invocations_for_inspection():
    fake = FakeLLMClient([
        Choice(finish_reason="stop", text="ok", tool_calls=[], tokens_in=1, tokens_out=1),
    ])
    schema = ToolSchema(name="t", description="", parameters={"type": "object"})

    await fake.complete([Message("user", "p")], [schema], max_tokens=1024)

    assert len(fake.calls) == 1
    assert fake.calls[0].messages[0].content == "p"
    assert fake.calls[0].tools[0].name == "t"
    assert fake.calls[0].max_tokens == 1024
