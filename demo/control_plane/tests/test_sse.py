"""Unit tests for the SSE broadcaster fan-out."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.sse import Broadcaster, sse_format


def test_sse_format_serializes_dict():
    frame = sse_format({"type": "tick", "score": 0.42})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame[len("data: ") :].strip())
    assert payload == {"type": "tick", "score": 0.42}


@pytest.mark.asyncio
async def test_publish_fans_out_to_all_subscribers():
    bc = Broadcaster()
    q1 = bc.subscribe("run-1")
    q2 = bc.subscribe("run-1")
    q_other = bc.subscribe("run-2")

    await bc.publish("run-1", {"type": "tick", "score": 0.1})

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1 == {"type": "tick", "score": 0.1}
    assert e2 == {"type": "tick", "score": 0.1}
    # The other run's queue is untouched.
    assert q_other.empty()


@pytest.mark.asyncio
async def test_unsubscribe_cleans_up():
    bc = Broadcaster()
    q = bc.subscribe("run-x")
    assert bc.subscriber_count("run-x") == 1
    bc.unsubscribe("run-x", q)
    assert bc.subscriber_count("run-x") == 0
