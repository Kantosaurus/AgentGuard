"""Unit tests for the per-run state machine. The real Scorer + docker client
are replaced with fakes so these exercise threshold logic and SSE emission
without booting the model or the daemon."""
from __future__ import annotations

import asyncio
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.buffers import Stream1Buffer, Stream2Buffer
from app.config import Config
from app.orchestrator import WorkerHandle
from app.runs import (
    RunManager,
    STATUS_COMPLETED,
    STATUS_KILLED,
    STATUS_MONITORING,
    STATUS_SUSPICIOUS,
)
from app.sse import Broadcaster


class _FakeWorker:
    def __init__(self):
        self.status = "running"
        self.killed = False
        self.removed = False

    def reload(self):
        pass

    def kill(self):
        self.killed = True
        self.status = "exited"

    def remove(self, force: bool = False):
        self.removed = True


def _make_handle() -> WorkerHandle:
    c = _FakeWorker()
    return WorkerHandle(c, pid=1234, name="agent-worker-test")


class _FakeOrchestrator:
    def __init__(self):
        self.handles: List[WorkerHandle] = []
        self.killed: List[WorkerHandle] = []

    def start_worker(self, run_id: str) -> WorkerHandle:
        h = _make_handle()
        self.handles.append(h)
        return h


class _FakeScorer:
    """Returns a pre-seeded list of scores (one per score() call)."""

    def __init__(self, scores: List[float]):
        self._scores = list(scores)
        self.calls = 0

    def score(self, s1, s2, mask) -> float:  # noqa: ANN001
        self.calls += 1
        if self._scores:
            return self._scores.pop(0)
        return 0.0


def _make_rm(
    scores: List[float], tick_sec: float = 0.01
) -> tuple[RunManager, _FakeOrchestrator, _FakeScorer, Broadcaster]:
    cfg = Config()
    # Override tick_sec via a cheap monkey-patch since Config is frozen.
    object.__setattr__(cfg, "tick_sec", tick_sec)
    object.__setattr__(cfg, "threshold", 0.5)

    bc = Broadcaster()
    orch = _FakeOrchestrator()
    scorer = _FakeScorer(scores)
    rm = RunManager.__new__(RunManager)
    rm.cfg = cfg
    rm.bc = bc
    rm.orch = orch
    rm.scorer = scorer
    rm.baseline = np.zeros((8, 32), dtype=np.float32)
    rm.runs = {}
    return rm, orch, scorer, bc


async def _drain_until_status(
    q: asyncio.Queue, timeout: float = 2.0
) -> List[dict]:
    """Drain events from q until a terminal 'status' event is seen."""
    events: List[dict] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError(f"never saw terminal status; saw: {events}")
        evt = await asyncio.wait_for(q.get(), timeout=remaining)
        events.append(evt)
        if evt.get("type") == "status":
            return events


@pytest.mark.asyncio
async def test_two_consecutive_over_threshold_kills(monkeypatch):
    rm, orch, scorer, bc = _make_rm(scores=[0.9, 0.9])

    async def _noop_fire(run, prompt):  # noqa: ANN001
        return None

    async def _no_window():
        return None

    monkeypatch.setattr(rm, "_fire_worker", _noop_fire)
    monkeypatch.setattr(rm, "_pull_window", _no_window)

    rid = await rm.start_run("attack!")
    q = bc.subscribe(rid)
    events = await _drain_until_status(q)

    kinds = [e.get("type") for e in events]
    assert "tick" in kinds
    assert events[-1] == {"type": "status", "status": STATUS_KILLED, "score": 0.9}
    assert orch.handles[0].container.killed  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_single_spike_does_not_kill(monkeypatch):
    rm, orch, scorer, bc = _make_rm(scores=[0.9, 0.1, 0.1])

    async def _noop_fire(run, prompt):  # noqa: ANN001
        return None

    async def _no_window():
        return None

    monkeypatch.setattr(rm, "_fire_worker", _noop_fire)
    monkeypatch.setattr(rm, "_pull_window", _no_window)

    rid = await rm.start_run("noisy but benign")
    q = bc.subscribe(rid)

    # Pull a few events to witness SUSPICIOUS → MONITORING and no kill.
    evt1 = await asyncio.wait_for(q.get(), timeout=2.0)
    evt2 = await asyncio.wait_for(q.get(), timeout=2.0)
    evt3 = await asyncio.wait_for(q.get(), timeout=2.0)

    statuses = [e["status"] for e in (evt1, evt2, evt3)]
    assert statuses[0] == STATUS_SUSPICIOUS
    assert STATUS_KILLED not in statuses
    run = rm.runs[rid]
    assert run.over_count == 0  # reset after the benign tick
    # Worker wasn't killed.
    assert not orch.handles[0].container.killed  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_worker_exit_completes_run(monkeypatch):
    rm, orch, scorer, bc = _make_rm(scores=[0.1, 0.1])

    async def _noop_fire(run, prompt):  # noqa: ANN001
        return None

    async def _no_window():
        return None

    monkeypatch.setattr(rm, "_fire_worker", _noop_fire)
    monkeypatch.setattr(rm, "_pull_window", _no_window)

    rid = await rm.start_run("hello")
    # Immediately mark the fake worker as exited; the next tick should
    # publish a COMPLETED status event.
    run = rm.runs[rid]
    run.worker.container.status = "exited"  # type: ignore[attr-defined]

    q = bc.subscribe(rid)
    events = await _drain_until_status(q)
    assert events[-1]["status"] == STATUS_COMPLETED


@pytest.mark.asyncio
async def test_ingest_event_publishes_log(monkeypatch):
    rm, orch, scorer, bc = _make_rm(scores=[0.1] * 20)

    async def _noop_fire(run, prompt):  # noqa: ANN001
        return None

    async def _no_window():
        return None

    monkeypatch.setattr(rm, "_fire_worker", _noop_fire)
    monkeypatch.setattr(rm, "_pull_window", _no_window)

    rid = await rm.start_run("x")
    q = bc.subscribe(rid)

    vec = [0.0] * 28
    await rm.ingest_event(rid, vec, "did a thing")

    # Poll until a log event appears (ticks may arrive in between).
    got_log = False
    for _ in range(20):
        evt = await asyncio.wait_for(q.get(), timeout=2.0)
        if evt.get("type") == "log":
            assert evt["line"] == "did a thing"
            got_log = True
            break
    assert got_log
    # And the Stream 2 buffer has the pushed event.
    assert len(rm.runs[rid].s2) == 1
