"""Generic GET/POST tool. The dangerous one - used by the LLM for exfil."""
from __future__ import annotations

from typing import Any

import httpx

from .base import Tool


class WebRequest(Tool):
    name = "web_request"
    description = ("Issue an HTTP GET or POST. Returns the response body "
                   "(first 4 KB).")
    is_external = True
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST"]},
            "url": {"type": "string"},
            "body": {"type": "string", "description": "Request body for POST."},
        },
        "required": ["method", "url"],
    }

    async def run(self, run_id: str, *, method: str, url: str,
                  body: str | None = None) -> str:
        if method.upper() not in ("GET", "POST"):
            return f"error: unsupported method: {method}"
        try:
            async with httpx.AsyncClient(timeout=10.0,
                                         follow_redirects=True) as client:
                if method.upper() == "GET":
                    r = await client.get(url)
                else:
                    r = await client.post(url, content=body or "")
        except httpx.HTTPError as e:
            return f"error: transport: {e}"
        if r.status_code >= 400:
            return f"error: HTTP {r.status_code}: {r.text[:200]}"
        return r.text[:4096]
