"""Write to /tmp/ only. Out-of-tree paths get rewritten to /tmp/<basename>.

The LLM's invocation is recorded faithfully (action event still says it
called write_file with the original path), but the side-effect is contained.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import Tool


class WriteFile(Tool):
    name = "write_file"
    description = ("Write text to a file. Paths under /tmp/ are kept as-is; "
                   "any other path is rewritten to /tmp/<basename>.")
    is_external = False
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    async def run(self, run_id: str, *, path: str, content: str) -> str:
        tmp_root = Path(os.environ.get("WRITE_FILE_TMP", "/tmp"))
        target = Path(path)
        try:
            target.relative_to(tmp_root)
        except ValueError:
            target = tmp_root / target.name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(content)
        except OSError as e:
            return f"error: {e}"
        if target != Path(path):
            return f"ok: wrote {len(content)} bytes to {target} (redirected from {path})"
        return f"ok: wrote {len(content)} bytes to {target}"
