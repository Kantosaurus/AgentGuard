"""Single-tenant mutex test for RunManager.start_run."""
from __future__ import annotations

import asyncio

import pytest

from app.config import Config
from app.errors import RunBusy
from app.runs import STATUS_COMPLETED, RunManager
from app.sse import Broadcaster


class _FakeOrch:
    """Minimal orchestrator double — start_worker returns a stub handle."""
    def __init__(self):
        self.started = []
    def start_worker(self, run_id):
        self.started.append(run_id)
        class _H:
            container_id = f"c-{run_id}"
            pid = 1
        return _H()
    async def kill_worker(self, *a, **kw):
        return None


class _NoopScorer:
    def score(self, *a, **kw): return 0.0


@pytest.mark.asyncio
async def test_second_start_while_busy_raises_runbusy(tmp_path):
    cfg = Config()
    # Config is a frozen dataclass; bypass with object.__setattr__ so the
    # scorer/baseline loaders look at a tmp path rather than the prod default.
    object.__setattr__(cfg, "checkpoint_path", str(tmp_path / "fake.pt"))
    bc = Broadcaster()
    rm = RunManager(cfg, bc, scorer=_NoopScorer(), orchestrator=_FakeOrch())

    rid1 = await rm.start_run("p1")
    assert rid1 in rm.runs

    with pytest.raises(RunBusy) as excinfo:
        await rm.start_run("p2")
    assert excinfo.value.retry_after_sec >= 0


@pytest.mark.asyncio
async def test_start_after_completion_succeeds(tmp_path):
    cfg = Config()
    # Config is a frozen dataclass; bypass with object.__setattr__ so the
    # scorer/baseline loaders look at a tmp path rather than the prod default.
    object.__setattr__(cfg, "checkpoint_path", str(tmp_path / "fake.pt"))
    bc = Broadcaster()
    rm = RunManager(cfg, bc, scorer=_NoopScorer(), orchestrator=_FakeOrch())

    rid1 = await rm.start_run("p1")
    rm.runs[rid1].status = STATUS_COMPLETED

    rid2 = await rm.start_run("p2")
    assert rid2 != rid1


import asyncio


@pytest.mark.asyncio
async def test_concurrent_starts_only_one_succeeds(tmp_path, monkeypatch):
    cfg = Config()
    object.__setattr__(cfg, "checkpoint_path", str(tmp_path / "fake.pt"))
    bc = Broadcaster()
    rm = RunManager(cfg, bc, scorer=_NoopScorer(), orchestrator=_FakeOrch())

    # Two concurrent start_run calls. Exactly one must succeed; the other must
    # raise RunBusy.
    results = await asyncio.gather(
        rm.start_run("p1"),
        rm.start_run("p2"),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, str)]
    busy_errors = [r for r in results if isinstance(r, RunBusy)]
    assert len(successes) == 1, f"expected 1 success, got {results!r}"
    assert len(busy_errors) == 1, f"expected 1 RunBusy, got {results!r}"
