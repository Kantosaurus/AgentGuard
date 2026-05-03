"""Tests for MinimaxM27Client.

Uses respx to mock the chat-completions and refresh endpoints. Exercises:
  * happy path tool-calls parsing
  * happy path stop-finish parsing
  * 401 -> refresh succeeds -> retry succeeds
  * 401 -> no refresh URL -> LLMAuthError
  * usage tokens propagated
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.llm.base import LLMAuthError, Message, ToolSchema
from app.llm.minimax import MinimaxM27Client

API = "https://api.minimax.io/v1/chat/completions"
REFRESH = "https://example.com/refresh"


def _completion_body(tool_calls=None, content=None, finish_reason="stop",
                     tokens_in=10, tokens_out=5):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {
        "id": "cmpl_1",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out,
                  "total_tokens": tokens_in + tokens_out},
    }


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_tool_calls_parsed():
    respx.post(API).mock(
        return_value=httpx.Response(200, json=_completion_body(
            tool_calls=[{
                "id": "call_xyz", "type": "function",
                "function": {"name": "web_search",
                             "arguments": json.dumps({"query": "weather"})},
            }],
            finish_reason="tool_calls",
        ))
    )
    client = MinimaxM27Client(model="minimax-m2.7", oauth_token="abc")
    out = await client.complete(
        [Message("user", "hi")],
        [ToolSchema("web_search", "x", {"type": "object"})],
    )
    assert out.finish_reason == "tool_calls"
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "web_search"
    assert out.tool_calls[0].args == {"query": "weather"}
    assert out.tokens_in == 10
    assert out.tokens_out == 5


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_stop():
    respx.post(API).mock(
        return_value=httpx.Response(200, json=_completion_body(
            content="hello there", finish_reason="stop",
        ))
    )
    client = MinimaxM27Client(model="minimax-m2.7", oauth_token="abc")
    out = await client.complete([Message("user", "hi")], [])
    assert out.finish_reason == "stop"
    assert out.text == "hello there"
    assert out.tool_calls == []


@pytest.mark.asyncio
@respx.mock
async def test_401_then_refresh_then_success():
    route = respx.post(API).mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json=_completion_body(content="ok",
                                                     finish_reason="stop")),
        ]
    )
    refresh_route = respx.post(REFRESH).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh"})
    )
    client = MinimaxM27Client(
        model="minimax-m2.7", oauth_token="stale", refresh_url=REFRESH,
    )
    out = await client.complete([Message("user", "hi")], [])
    assert out.text == "ok"
    assert refresh_route.call_count == 1
    assert route.call_count == 2
    assert client.oauth_token == "fresh"


@pytest.mark.asyncio
@respx.mock
async def test_401_no_refresh_url_raises_auth_error():
    respx.post(API).mock(return_value=httpx.Response(401, json={"error": "x"}))
    client = MinimaxM27Client(model="minimax-m2.7", oauth_token="stale")
    with pytest.raises(LLMAuthError):
        await client.complete([Message("user", "hi")], [])


@pytest.mark.asyncio
@respx.mock
async def test_messages_serialised_with_tool_role():
    captured: dict = {}
    def _cb(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion_body(content="ok"))
    respx.post(API).mock(side_effect=_cb)

    client = MinimaxM27Client(model="minimax-m2.7", oauth_token="t")
    msgs = [
        Message("system", "S"),
        Message("user", "U"),
        Message("assistant", "A"),
        Message("tool", "T", tool_call_id="c1", name="web_search"),
    ]
    await client.complete(msgs, [])

    body_msgs = captured["body"]["messages"]
    assert body_msgs[3] == {"role": "tool", "content": "T",
                            "tool_call_id": "c1", "name": "web_search"}
