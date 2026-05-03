"""Read any file the worker user can read. Returns first 4 KB."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool

_MAX_BYTES = 4096


class ReadFile(Tool):
    name = "read_file"
    description = ("Read a file from the local filesystem and return its "
                   "contents (first 4 KB).")
    is_external = False
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string",
                                "description": "Absolute or relative path."}},
        "required": ["path"],
    }

    async def run(self, run_id: str, *, path: str) -> str:
        try:
            data = Path(path).read_bytes()
        except FileNotFoundError:
            return f"error: not found: {path}"
        except PermissionError:
            return f"error: permission denied: {path}"
        except OSError as e:
            return f"error: {e}"
        try:
            return data[:_MAX_BYTES].decode("utf-8", errors="replace")
        except Exception as e:
            return f"error: decode: {e}"
