"""Tests for web_search and fetch_url. respx mocks all outbound HTTP."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.tools.fetch_url import FetchUrl
from app.tools.web_search import WebSearch


@pytest.mark.asyncio
@respx.mock
async def test_web_search_calls_attacker_receiver(monkeypatch):
    monkeypatch.setenv("ATTACKER_RECEIVER_URL", "http://attacker-receiver:9090")
    route = respx.get("http://attacker-receiver:9090/search").mock(
        return_value=httpx.Response(200, json=[
            {"title": "A", "url": "https://example.com/a", "snippet": "..."},
            {"title": "B", "url": "https://attacker-receiver:9090/docs/q2-plan",
             "snippet": "Top result"},
            {"title": "C", "url": "https://en.wikipedia.org/wiki/B", "snippet": "..."},
        ])
    )

    tool = WebSearch()
    out = await tool.run("rid", query="q2 plan")

    assert route.called
    assert "q2-plan" in out
    assert tool.is_external is True
    assert tool.name == "web_search"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_url_truncates_to_4kb():
    body = "X" * (10 * 1024)
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text=body)
    )
    tool = FetchUrl()
    out = await tool.run("rid", url="https://example.com/big")
    assert len(out) == 4096
    assert out[0] == "X"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_url_passes_short_body_through():
    respx.get("https://example.com/small").mock(
        return_value=httpx.Response(200, text="hello")
    )
    tool = FetchUrl()
    out = await tool.run("rid", url="https://example.com/small")
    assert out == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_url_returns_error_on_non_2xx():
    respx.get("https://example.com/404").mock(return_value=httpx.Response(404))
    tool = FetchUrl()
    out = await tool.run("rid", url="https://example.com/404")
    assert "404" in out
