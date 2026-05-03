"""LLM-facing URL fetcher. GET only, body truncated to 4 KB."""
from __future__ import annotations

from typing import Any

import httpx

from .base import Tool

_MAX_BYTES = 4096


class FetchUrl(Tool):
    name = "fetch_url"
    description = "Fetch a URL via GET and return the response body (first 4 KB)."
    is_external = True
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "URL to fetch."}},
        "required": ["url"],
    }

    async def run(self, run_id: str, *, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0,
                                         follow_redirects=True) as client:
                r = await client.get(url)
        except httpx.HTTPError as e:
            return f"error: transport: {e}"
        if r.status_code >= 400:
            return f"error: HTTP {r.status_code}"
        return r.text[:_MAX_BYTES]
