"""FastAPI entrypoint for the agent worker.

POST /execute {run_id, prompt} -> {behavior: name}
    Routes the prompt to the matching behavior coroutine and kicks it off via
    asyncio.create_task (fire-and-forget, returns immediately).

GET  /health -> {ok: true}
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from .router import route

logger = logging.getLogger("agent_worker")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="agent-worker")


class ExecuteRequest(BaseModel):
    run_id: str
    prompt: str


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    name, fn = route(req.prompt)
    logger.info("execute run_id=%s behavior=%s prompt=%r", req.run_id, name, req.prompt)

    async def _runner():
        try:
            await fn(req.run_id, req.prompt)
        except Exception as exc:
            logger.exception("behavior %s crashed: %s", name, exc)

    asyncio.create_task(_runner())
    return {"behavior": name}


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
