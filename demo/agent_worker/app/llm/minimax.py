"""MiniMax M2.7 chat-completions adapter (OpenAI-compatible endpoint).

Sends OAuth bearer in the Authorization header. On 401, attempts ONE refresh
against AGENT_OAUTH_REFRESH_URL if configured, then retries the original
request. Any other non-2xx response surfaces as LLMError.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Sequence

import httpx

from .base import (
    Choice,
    LLMAuthError,
    LLMClient,
    LLMError,
    Message,
    ToolCall,
    ToolSchema,
)

log = logging.getLogger("agent_worker.llm.minimax")

DEFAULT_API_URL = "https://api.minimax.io/v1/chat/completions"
DEFAULT_TIMEOUT_SEC = 60.0


def _serialise_message(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_call_id is not None:
        out["tool_call_id"] = m.tool_call_id
    if m.name is not None:
        out["name"] = m.name
    return out


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    if not raw:
        return []
    out: list[ToolCall] = []
    for tc in raw:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        out.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""),
                            args=args, latency_ms=0.0))
    return out


class MinimaxM27Client(LLMClient):
    def __init__(
        self,
        *,
        model: str,
        oauth_token: str,
        refresh_url: str | None = None,
        api_url: str | None = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ):
        self.model = model
        self.oauth_token = oauth_token
        self.refresh_url = refresh_url
        self.api_url = api_url or DEFAULT_API_URL
        self.timeout_sec = timeout_sec

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_tokens: int = 2048,
    ) -> Choice:
        body = self._build_body(messages, tools, max_tokens)
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            t0 = time.monotonic()
            resp = await client.post(self.api_url, json=body, headers=self._headers())
            if resp.status_code == 401 and self.refresh_url:
                await self._refresh(client)
                resp = await client.post(self.api_url, json=body, headers=self._headers())
            if resp.status_code == 401:
                raise LLMAuthError("MiniMax 401 and refresh unavailable or failed")
            if resp.status_code >= 400:
                raise LLMError(f"MiniMax HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            dt_ms = (time.monotonic() - t0) * 1000
            log.info("minimax complete dt_ms=%.1f tokens=%s", dt_ms,
                     data.get("usage", {}))
            return _parse_response(data)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.oauth_token}",
                "Content-Type": "application/json"}

    def _build_body(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_serialise_message(m) for m in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = [t.to_openai_dict() for t in tools]
            body["tool_choice"] = "auto"
        return body

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        assert self.refresh_url is not None
        resp = await client.post(self.refresh_url,
                                 data={"refresh_token": self.oauth_token})
        if resp.status_code >= 400:
            raise LLMAuthError(f"refresh HTTP {resp.status_code}: {resp.text[:200]}")
        token = resp.json().get("access_token")
        if not token:
            raise LLMAuthError("refresh response missing access_token")
        self.oauth_token = token


def _parse_response(data: dict[str, Any]) -> Choice:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("MiniMax response had no choices")
    c0 = choices[0]
    msg = c0.get("message") or {}
    finish = c0.get("finish_reason") or "stop"
    if finish not in ("stop", "tool_calls", "length"):
        finish = "stop"
    usage = data.get("usage") or {}
    return Choice(
        finish_reason=finish,
        text=msg.get("content"),
        tool_calls=_parse_tool_calls(msg.get("tool_calls")),
        tokens_in=int(usage.get("prompt_tokens", 0)),
        tokens_out=int(usage.get("completion_tokens", 0)),
    )
