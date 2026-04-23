"""Benign behavior coroutines: summarize, search, calculate, list_files.

Each coroutine emits a user_message event, performs one or two real tool
actions, emits matching tool_call / tool_result events, and finishes with an
llm_response event. Payloads are deliberately small so Stream-1 CPU stays low.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

from ..events import emit

FIXTURES = Path(os.environ.get("AGENT_FIXTURES", "/app/fixtures"))


async def summarize(run_id: str, prompt: str) -> None:
    await emit(
        run_id,
        {
            "type": "user_message",
            "tokens_in": len(prompt.split()),
            "tokens_out": 0,
            "user_initiated": True,
            "dt_prev_ms": 0,
        },
        f"USER> {prompt}",
    )

    notes_path = FIXTURES / "notes.txt"
    try:
        data = notes_path.read_text()
    except Exception:
        data = ""

    await emit(
        run_id,
        {
            "type": "tool_call",
            "tool": "read_file",
            "latency_ms": 0,
            "user_initiated": False,
            "dt_prev_ms": 10,
            "has_tool_calls": True,
        },
        f"TOOL> read_file({notes_path})",
    )
    await emit(
        run_id,
        {
            "type": "tool_result",
            "tool": "read_file",
            "latency_ms": 5,
            "tokens_in": len(data.split()),
            "tokens_out": 0,
            "user_initiated": False,
            "dt_prev_ms": 5,
        },
        f"RES> {len(data)} bytes",
    )
    await emit(
        run_id,
        {
            "type": "llm_response",
            "tokens_out": 30,
            "user_initiated": False,
            "dt_prev_ms": 150,
        },
        "LLM> Summary: short meeting notes about Q2 planning and demo prep.",
    )


async def search(run_id: str, prompt: str) -> None:
    await emit(
        run_id,
        {"type": "user_message", "user_initiated": True, "dt_prev_ms": 0,
         "tokens_in": len(prompt.split())},
        f"USER> {prompt}",
    )
    await emit(
        run_id,
        {
            "type": "tool_call",
            "tool": "web_search",
            "has_tool_calls": True,
            "external_source": True,
            "dt_prev_ms": 20,
        },
        "TOOL> web_search(demo)",
    )

    # Real network call, best-effort
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.get("https://api.duckduckgo.com/?q=demo&format=json")
    except Exception:
        pass

    await emit(
        run_id,
        {
            "type": "tool_result",
            "tool": "web_search",
            "external_source": True,
            "dt_prev_ms": 400,
            "latency_ms": 300,
        },
        "RES> 3 results",
    )
    await emit(
        run_id,
        {"type": "llm_response", "dt_prev_ms": 120, "tokens_out": 25},
        "LLM> Here are 3 search results for your query.",
    )


async def calculate(run_id: str, prompt: str) -> None:
    await emit(
        run_id,
        {"type": "user_message", "user_initiated": True, "dt_prev_ms": 0,
         "tokens_in": len(prompt.split())},
        f"USER> {prompt}",
    )

    # Tiny in-process arithmetic loop — stays well under 0.5s.
    x = 0
    for i in range(200_000):
        x += i

    await emit(
        run_id,
        {"type": "llm_response", "dt_prev_ms": 50, "tokens_out": 8},
        f"LLM> = {x}",
    )


async def list_files(run_id: str, prompt: str) -> None:
    await emit(
        run_id,
        {"type": "user_message", "user_initiated": True, "dt_prev_ms": 0,
         "tokens_in": len(prompt.split())},
        f"USER> {prompt}",
    )
    await emit(
        run_id,
        {
            "type": "tool_call",
            "tool": "list_directory",
            "has_tool_calls": True,
            "dt_prev_ms": 10,
        },
        f"TOOL> list_directory({FIXTURES})",
    )

    try:
        files = os.listdir(FIXTURES)
    except Exception:
        files = []

    await emit(
        run_id,
        {
            "type": "tool_result",
            "tool": "list_directory",
            "dt_prev_ms": 10,
            "latency_ms": 5,
        },
        f"RES> {files}",
    )
    await emit(
        run_id,
        {"type": "llm_response", "dt_prev_ms": 80, "tokens_out": 15},
        f"LLM> Files: {', '.join(files) if files else '(empty)'}",
    )
