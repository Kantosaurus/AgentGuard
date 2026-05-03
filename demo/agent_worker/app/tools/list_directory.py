"""List the first 100 entries of a directory."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool

_MAX_ENTRIES = 100


class ListDirectory(Tool):
    name = "list_directory"
    description = "List up to 100 entries of a directory."
    is_external = False
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def run(self, run_id: str, *, path: str) -> str:
        p = Path(path)
        if not p.is_dir():
            return f"error: not a directory: {path}"
        try:
            entries = sorted(e.name for e in p.iterdir())
        except OSError as e:
            return f"error: {e}"
        return "\n".join(entries[:_MAX_ENTRIES])
