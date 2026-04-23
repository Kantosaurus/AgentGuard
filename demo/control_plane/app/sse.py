"""Per-run async SSE broadcaster.

Subscribers register with ``subscribe(run_id)`` and receive their own
``asyncio.Queue`` that receives every ``publish(run_id, event)`` dict for the
run. ``sse_format(event)`` converts a dict to the SSE wire format.
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Dict, List


_HISTORY_LIMIT = 1024  # per run_id; plenty for a 60 s run at 5 s ticks + events


class Broadcaster:
    """Fan-out of dict events to per-run subscriber queues.

    Keeps a bounded replay buffer per run_id so late-joining subscribers (the
    frontend, which subscribes after POST /run returns) still see events that
    fired between ``start_run`` and the SSE connection setup.
    """

    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._history: Dict[str, List[dict]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for past in self._history.get(run_id, []):
            q.put_nowait(past)
        self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        lst = self._queues.get(run_id)
        if not lst:
            return
        try:
            lst.remove(q)
        except ValueError:
            pass
        if not lst:
            self._queues.pop(run_id, None)

    async def publish(self, run_id: str, event: dict) -> None:
        hist = self._history[run_id]
        hist.append(event)
        if len(hist) > _HISTORY_LIMIT:
            del hist[: len(hist) - _HISTORY_LIMIT]
        for q in list(self._queues.get(run_id, [])):
            await q.put(event)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._queues.get(run_id, []))

    def reset(self, run_id: str) -> None:
        """Drop cached history for a run (called on terminal status + timeout)."""
        self._history.pop(run_id, None)


def sse_format(event: dict) -> str:
    """Format a dict as one SSE ``data:`` frame terminated by a blank line."""
    return f"data: {json.dumps(event)}\n\n"
