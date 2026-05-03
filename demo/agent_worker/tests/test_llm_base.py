"""Shape tests for the LLMClient ABC, dataclasses, and exception types."""
from __future__ import annotations

import pytest

from app.llm.base import (
    Choice,
    LLMAuthError,
    LLMClient,
    LLMError,
    Message,
    ToolCall,
    ToolSchema,
)


def test_message_dataclass_roundtrips():
    m = Message(role="user", content="hello")
    assert m.role == "user"
    assert m.content == "hello"
    assert m.tool_call_id is None
    assert m.name is None


def test_tool_message_carries_tool_call_id():
    m = Message(role="tool", content="ok", tool_call_id="call_1", name="web_search")
    assert m.tool_call_id == "call_1"
    assert m.name == "web_search"


def test_toolcall_dataclass():
    tc = ToolCall(id="c1", name="web_search", args={"query": "x"}, latency_ms=12.5)
    assert tc.id == "c1"
    assert tc.args["query"] == "x"
    assert tc.latency_ms == 12.5


def test_choice_stop_finish():
    c = Choice(finish_reason="stop", text="done", tool_calls=[], tokens_in=10, tokens_out=5)
    assert c.finish_reason == "stop"
    assert c.text == "done"
    assert c.tool_calls == []


def test_choice_tool_calls_finish():
    tc = ToolCall(id="c1", name="web_search", args={"query": "x"}, latency_ms=0.0)
    c = Choice(finish_reason="tool_calls", text=None, tool_calls=[tc],
               tokens_in=20, tokens_out=8)
    assert c.finish_reason == "tool_calls"
    assert len(c.tool_calls) == 1


def test_tool_schema_serialises():
    schema = ToolSchema(
        name="web_search",
        description="Search the web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    d = schema.to_openai_dict()
    assert d["type"] == "function"
    assert d["function"]["name"] == "web_search"
    assert d["function"]["description"] == "Search the web."
    assert d["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_llm_client_is_abstract():
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_llm_error_hierarchy():
    assert issubclass(LLMAuthError, LLMError)
    assert issubclass(LLMError, Exception)
