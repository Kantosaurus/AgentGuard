"""Per-run lifecycle: buffers, tick loop, threshold logic, SSE emission.

A ``RunManager`` owns the shared scorer, orchestrator and baseline, and spawns
one ``_run_loop`` coroutine per ``start_run`` call. Each run has its own
``Run`` dataclass (mutable status + score + buffers) and its own worker
container.

Tick cadence: once every ``cfg.tick_sec`` (5 s default).
Kill rule: score > threshold on 2 consecutive ticks.
Completion: worker container exits of its own accord before the kill rule
fires — treated as a benign completion.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx
import numpy as np

from .baseline import load_baseline, load_norm
from .buffers import Stream1Buffer, Stream2Buffer
from .config import Config
from .inference import Scorer
from .orchestrator import Orchestrator, WorkerHandle
from .sse import Broadcaster

log = logging.getLogger("agentguard.runs")

STATUS_MONITORING = "MONITORING"
STATUS_SUSPICIOUS = "SUSPICIOUS"
STATUS_KILLED = "KILLED"
STATUS_COMPLETED = "COMPLETED"
_TERMINAL = {STATUS_KILLED, STATUS_COMPLETED}


@dataclass
class Run:
    run_id: str
    status: str = STATUS_MONITORING
    score: float = 0.0
    over_count: int = 0
    worker: Optional[WorkerHandle] = None
    s1: Optional[Stream1Buffer] = None
    s2: Optional[Stream2Buffer] = None
    tick_index: int = 0
    started_at: float = field(default_factory=time.time)


class RunManager:
    """Owns live runs, the scorer, and the orchestrator."""

    def __init__(
        self,
        cfg: Config,
        bc: Broadcaster,
        *,
        scorer: Optional[Scorer] = None,
        orchestrator: Optional[Orchestrator] = None,
    ):
        self.cfg = cfg
        self.bc = bc
        self.orch = orchestrator if orchestrator is not None else Orchestrator(cfg)
        mean, std = load_norm(cfg)
        self.scorer = scorer if scorer is not None else Scorer(cfg, mean, std)
        self.baseline = load_baseline(cfg)
        self.runs: Dict[str, Run] = {}

    # ------------------------------------------------------------------ public

    async def start_run(self, prompt: str) -> str:
        rid = uuid.uuid4().hex[:10]
        handle = self.orch.start_worker(rid)

        # Point telemetry-collector at the worker's PID. Best-effort: the
        # collector may not be up (unit tests), in which case we log and move
        # on — the tick loop will still score using the baseline.
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                await c.post(
                    f"{self.cfg.telemetry_url}/target/{handle.pid}"
                )
        except Exception as e:  # noqa: BLE001
            log.warning("could not reach telemetry-collector: %s", e)

        run = Run(
            run_id=rid,
            worker=handle,
            s1=Stream1Buffer.from_baseline(self.baseline),
            s2=Stream2Buffer(max_len=64, dim=28),
        )
        self.runs[rid] = run
        asyncio.create_task(self._run_loop(run, prompt))
        return rid

    async def ingest_event(
        self, run_id: str, vec_28: list[float], log_line: str
    ) -> None:
        run = self.runs.get(run_id)
        if run is None:
            return
        vec = np.asarray(vec_28, dtype=np.float32)
        if vec.shape == (28,):
            run.s2.push(vec)
        else:
            log.warning(
                "ingest_event: dropping event with shape %s for run %s",
                vec.shape,
                run_id,
            )
        await self.bc.publish(run_id, {"type": "log", "line": log_line})

    # ----------------------------------------------------------------- internal

    async def _fire_worker(self, run: Run, prompt: str) -> None:
        """Fire-and-forget POST to the worker's /execute endpoint."""
        url = f"http://agent-worker-{run.run_id}:{self.cfg.worker_port}/execute"
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                await c.post(
                    url, json={"run_id": run.run_id, "prompt": prompt}
                )
        except Exception as e:  # noqa: BLE001
            # The worker may not be reachable (unit tests, missing image).
            # Keep the tick loop alive regardless.
            log.warning("could not POST to %s: %s", url, e)
            await self.bc.publish(
                run.run_id,
                {"type": "log", "line": f"control-plane: worker POST failed: {e}"},
            )

    async def _pull_window(self) -> Optional[np.ndarray]:
        """Pull the current 8x32 telemetry window from the collector."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.cfg.telemetry_url}/window")
                r.raise_for_status()
                payload = r.json()
                arr = np.asarray(payload["data"], dtype=np.float32)
                if arr.shape != (8, 32):
                    log.warning(
                        "telemetry /window returned shape %s; expected (8, 32)",
                        arr.shape,
                    )
                    return None
                return arr
        except Exception as e:  # noqa: BLE001
            log.warning("telemetry /window unreachable: %s", e)
            return None

    async def _run_loop(self, run: Run, prompt: str) -> None:
        """Main per-run scoring loop. Runs until a terminal status is reached."""
        # Kick the worker off (fire-and-forget).
        await self._fire_worker(run, prompt)

        try:
            while run.status not in _TERMINAL:
                await asyncio.sleep(self.cfg.tick_sec)
                run.tick_index += 1

                # Pull the authoritative 8x32 window from the collector and
                # use it as the Stream 1 context. If the collector is down,
                # keep the last-known buffer instead of zeroing out.
                win = await self._pull_window()
                if win is not None:
                    run.s1 = Stream1Buffer.from_baseline(win)

                s1 = run.s1.current()
                s2, mask = run.s2.current()
                try:
                    run.score = self.scorer.score(s1, s2, mask)
                except Exception as e:  # noqa: BLE001
                    log.error("scorer failed on run %s: %s", run.run_id, e)
                    await self.bc.publish(
                        run.run_id,
                        {"type": "log", "line": f"scorer error: {e}"},
                    )
                    continue

                over = run.score > self.cfg.threshold
                run.over_count = run.over_count + 1 if over else 0

                if over:
                    run.status = STATUS_SUSPICIOUS
                else:
                    run.status = STATUS_MONITORING

                # Kill on 2-consecutive-tick threshold exceedance.
                if run.over_count >= 2:
                    run.status = STATUS_KILLED
                    if run.worker is not None:
                        run.worker.kill()
                    await self.bc.publish(
                        run.run_id,
                        {
                            "type": "tick",
                            "score": run.score,
                            "status": run.status,
                            "stream1_last": s1[-1].tolist(),
                        },
                    )
                    await self.bc.publish(
                        run.run_id,
                        {
                            "type": "status",
                            "status": STATUS_KILLED,
                            "score": run.score,
                        },
                    )
                    break

                # Did the worker exit on its own (benign completion)?
                if run.worker is not None:
                    run.worker.reload()
                    if run.worker.status in ("exited", "dead", "removing"):
                        run.status = STATUS_COMPLETED
                        await self.bc.publish(
                            run.run_id,
                            {
                                "type": "tick",
                                "score": run.score,
                                "status": run.status,
                                "stream1_last": s1[-1].tolist(),
                            },
                        )
                        await self.bc.publish(
                            run.run_id,
                            {
                                "type": "status",
                                "status": STATUS_COMPLETED,
                                "score": run.score,
                            },
                        )
                        break

                # Normal tick publish.
                await self.bc.publish(
                    run.run_id,
                    {
                        "type": "tick",
                        "score": run.score,
                        "status": run.status,
                        "stream1_last": s1[-1].tolist(),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("run loop crashed for %s: %s", run.run_id, e)
            if run.worker is not None:
                run.worker.kill()
            run.status = STATUS_KILLED
            await self.bc.publish(
                run.run_id,
                {"type": "status", "status": STATUS_KILLED, "score": run.score},
            )
