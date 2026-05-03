"""Run a shell command with cpu/mem ulimits and a 30 s timeout.

The container itself is the security boundary. ulimit + timeout protect the
run from the LLM accidentally building an infinite loop.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from .base import Tool


def _timeout_sec() -> float:
    return float(os.environ.get("SHELL_EXEC_TIMEOUT_SEC", "30"))


_PRELUDE = "ulimit -t 30 -v 524288; "


class ShellExec(Tool):
    name = "shell_exec"
    description = "Execute a bash command. CPU 30 s, memory 512 MB, wall 30 s."
    is_external = False
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
        "required": ["cmd"],
    }

    async def run(self, run_id: str, *, cmd: str) -> str:
        full = _PRELUDE + cmd
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", full,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(),
                                               timeout=_timeout_sec())
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return f"error: timed out after {_timeout_sec()}s"
        out = stdout.decode("utf-8", errors="replace")[:4096]
        if proc.returncode != 0:
            return f"error: exit {proc.returncode}: {out}"
        return out
