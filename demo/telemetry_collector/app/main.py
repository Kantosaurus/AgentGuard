"""Telemetry collector service.

Samples /proc for a target PID at 2 Hz, aggregates 30 s windows every 5 s, and
exposes the current ``(8, 32)`` sliding Stream-1 tensor on GET /window for the
control plane to consume.

Endpoints:
    POST /target/{pid}  — start/switch sampling on a PID (usually the worker's
                          host PID from ``docker inspect``).
    GET  /window        — {"shape": [8, 32], "data": <2D list of floats>}.
    GET  /health        — liveness probe.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI

from .aggregator import Aggregator
from .proc_sampler import sample_once

# 0.5 s sample period → 2 Hz. 5 s emit period → 0.2 Hz. Matches plan's timing.
SAMPLE_PERIOD_S = 0.5
EMIT_PERIOD_S = 5.0
WINDOW_SIZE_S = 30.0
SEQ_CONTEXT = 8

app = FastAPI(title="agentguard-telemetry-collector")
_agg = Aggregator(window_size=WINDOW_SIZE_S, seq_context=SEQ_CONTEXT)
_target_pid: int | None = None
_tasks: list[asyncio.Task] = []


async def _sample_loop() -> None:
    """Sample the current target PID every SAMPLE_PERIOD_S until cancelled."""
    while True:
        pid = _target_pid
        if pid is not None:
            try:
                _agg.add(sample_once(pid))
            except Exception:
                # Never let sampling errors kill the loop; the next tick retries.
                pass
        await asyncio.sleep(SAMPLE_PERIOD_S)


async def _emit_loop() -> None:
    """Build one 30 s feature window per EMIT_PERIOD_S tick."""
    while True:
        try:
            _agg.emit_window(time.time())
        except Exception:
            pass
        await asyncio.sleep(EMIT_PERIOD_S)


@app.on_event("startup")
async def _boot() -> None:
    _tasks.append(asyncio.create_task(_sample_loop()))
    _tasks.append(asyncio.create_task(_emit_loop()))


@app.on_event("shutdown")
async def _teardown() -> None:
    for t in _tasks:
        t.cancel()
    for t in _tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    _tasks.clear()


@app.post("/target/{pid}")
async def set_target(pid: int) -> dict:
    """Point the sampling loop at ``pid`` (the worker's host PID)."""
    global _target_pid
    _target_pid = pid
    return {"ok": True, "pid": pid}


@app.get("/target")
async def get_target() -> dict:
    return {"pid": _target_pid}


@app.get("/window")
async def get_window() -> dict:
    """Return the current sliding Stream-1 tensor as plain JSON."""
    w = _agg.current_window()
    return {"shape": list(w.shape), "data": w.tolist()}


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
