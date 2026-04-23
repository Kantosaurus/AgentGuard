"""FastAPI entry point for the AgentGuard control plane.

Endpoints:
  * GET  /health                 — liveness probe.
  * POST /run                    — start a new run (spawns worker + tick loop).
  * POST /events                 — agent-worker posts action-event vectors.
  * GET  /runs/{run_id}/stream   — server-sent events for a run.

Model load, scorer construction, and docker client creation all happen at
startup time so /run is fast.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import Config
from .runs import RunManager
from .sse import Broadcaster, sse_format

logging.basicConfig(
    level=os.environ.get("AGENTGUARD_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("agentguard.main")


class RunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4096)


class RunResponse(BaseModel):
    run_id: str


class EventRequest(BaseModel):
    run_id: str
    vec: List[float]
    log: str = ""


app = FastAPI(title="AgentGuard control plane", version="0.1.0")

# The frontend is served on a different host port than the control plane
# (:3001 vs :8000), so browsers treat /run and /runs/*/stream as cross-origin.
# Allow any localhost origin — this is a dev demo, not a public service.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_cfg = Config()
_bc = Broadcaster()
_rm: Optional[RunManager] = None
_rm_error: Optional[str] = None


def _try_build_run_manager() -> None:
    """Construct the RunManager lazily so /health stays up even if the
    checkpoint or docker socket isn't available (CI/tests)."""
    global _rm, _rm_error
    if _rm is not None or _rm_error is not None:
        return
    try:
        _rm = RunManager(_cfg, _bc)
        log.info("RunManager ready (threshold=%.3f)", _cfg.threshold)
    except Exception as e:  # noqa: BLE001
        _rm_error = f"{type(e).__name__}: {e}"
        log.warning("RunManager unavailable: %s", _rm_error)


@app.on_event("startup")
async def _startup() -> None:
    _try_build_run_manager()


def _require_rm() -> RunManager:
    if _rm is None:
        _try_build_run_manager()
    if _rm is None:
        raise HTTPException(
            status_code=503,
            detail=f"RunManager unavailable: {_rm_error or 'not initialized'}",
        )
    return _rm


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "run_manager_ready": _rm is not None,
        "run_manager_error": _rm_error,
    }


@app.post("/run", response_model=RunResponse)
async def start_run(req: RunRequest) -> RunResponse:
    rm = _require_rm()
    rid = await rm.start_run(req.prompt)
    return RunResponse(run_id=rid)


@app.post("/events")
async def post_event(req: EventRequest) -> dict:
    rm = _require_rm()
    await rm.ingest_event(req.run_id, req.vec, req.log)
    return {"ok": True}


@app.get("/runs/{run_id}/stream")
async def stream(run_id: str, request: Request) -> StreamingResponse:
    q = _bc.subscribe(run_id)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield sse_format(evt)
                    if evt.get("type") == "status":
                        # Terminal event delivered; close the stream.
                        break
                except asyncio.TimeoutError:
                    yield sse_format({"type": "heartbeat"})
        finally:
            _bc.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")
