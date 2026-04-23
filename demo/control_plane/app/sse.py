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


class Broadcaster:
    """Fan-out of dict events to per-run subscriber queues."""

    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
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
        for q in list(self._queues.get(run_id, [])):
            await q.put(event)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._queues.get(run_id, []))


def sse_format(event: dict) -> str:
    """Format a dict as one SSE ``data:`` frame terminated by a blank line."""
    return f"data: {json.dumps(event)}\n\n"
