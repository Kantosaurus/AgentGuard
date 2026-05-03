"""FastAPI entrypoint for the agent worker.

POST /execute {run_id, prompt} -> {behavior: name}
    AGENT_MODE=llm (default)   -> agent_loop.run_agent (real LLM tool-use).
    AGENT_MODE=scripted         -> keyword router -> behavior coroutine.

GET  /health -> {ok: true}
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel

from .agent_loop import run_agent as _run_agent_real
from .llm import from_env as _llm_from_env
from .router import route
from .tools import build_default_registry

logger = logging.getLogger("agent_worker")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="agent-worker")

_REGISTRY = build_default_registry()


class ExecuteRequest(BaseModel):
    run_id: str
    prompt: str


# Module-level indirection so tests can monkeypatch.
async def _run_agent_async(run_id: str, prompt: str) -> None:
    llm = _llm_from_env()
    await _run_agent_real(run_id, prompt, llm=llm, registry=_REGISTRY)


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    mode = os.environ.get("AGENT_MODE", "llm").lower()

    if mode == "llm":
        async def _runner():
            try:
                await _run_agent_async(req.run_id, req.prompt)
            except Exception as exc:
                logger.exception("agent_loop crashed: %s", exc)
        asyncio.create_task(_runner())
        return {"behavior": "llm"}

    # scripted fallback
    name, fn = route(req.prompt)
    logger.info("execute (scripted) run_id=%s behavior=%s prompt=%r",
                req.run_id, name, req.prompt)

    async def _runner_scripted():
        try:
            await fn(req.run_id, req.prompt)
        except Exception as exc:
            logger.exception("behavior %s crashed: %s", name, exc)
    asyncio.create_task(_runner_scripted())
    return {"behavior": name}


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
