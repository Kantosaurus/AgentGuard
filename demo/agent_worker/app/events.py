"""Stream-2 action-event encoder + emitter for the agent worker.

Thin wrapper over ``data.preprocessing.encode_event`` (the canonical per-event
Stream-2 encoder in the main repo, which returns a 28-dim list[float]).
Because the behaviors in this package pass a friendlier event shape (``type``,
``latency_ms``, ``dt_prev_ms``, ``external_source``), this module normalizes
those keys to the canonical schema that ``encode_event`` consumes:
``event``, ``latency``, ``timestamp``/``prev_timestamp``, ``source``.

The ``emit`` coroutine POSTs ``{run_id, vec, log}`` to
``http://control-plane:8000/events``. Network failures are swallowed so the
behavior coroutines keep running even when the control-plane is unreachable
(useful for smoke-testing the worker in isolation).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

# Ensure the main repo is importable inside the container where we COPY . /workspace.
if "/workspace" not in sys.path:
    sys.path.insert(0, "/workspace")

from data.preprocessing import encode_event as _canonical_encode_event  # noqa: E402

CONTROL_PLANE = os.environ.get("CONTROL_PLANE_URL", "http://control-plane:8000")
_HTTP_TIMEOUT = float(os.environ.get("AGENT_EMIT_TIMEOUT", "2.0"))

# Per-run previous-timestamp tracker so dt_prev_ms translates into a proper
# prev_timestamp argument for the canonical encoder.
_PREV_TS: dict[str, datetime] = {}


def _normalize_event(evt: dict[str, Any], run_id: str | None = None) -> tuple[dict[str, Any], datetime | None]:
    """Translate the demo's friendlier event shape into the canonical schema.

    Returns (canonical_event_dict, prev_timestamp_or_None).
    """
    # Start from a shallow copy so we don't mutate the caller's dict.
    out: dict[str, Any] = dict(evt)

    # event/type alias — data.preprocessing uses "event"
    if "event" not in out and "type" in out:
        out["event"] = out.pop("type")

    # latency/latency_ms alias — canonical is "latency" (seconds-ish; the
    # encoder just min-max normalizes against MAX_LATENCY=60, so passing a
    # seconds number is fine for a demo scale).
    if "latency" not in out and "latency_ms" in out:
        try:
            out["latency"] = float(out.pop("latency_ms")) / 1000.0
        except Exception:
            out.pop("latency_ms", None)
            out["latency"] = 0.0

    # source/external_source alias — canonical encoder sets vec[26] = 1.0 when
    # source is something other than "internal"/"unknown"/"". Map the boolean.
    if "source" not in out and "external_source" in out:
        out["source"] = "external" if out.pop("external_source") else "internal"

    # has_tool_calls / user_initiated kept as-is (same keys).

    # timestamp handling: prefer a caller-supplied iso timestamp. Otherwise,
    # synthesize one using dt_prev_ms (ms since previous event in this run).
    prev_ts: datetime | None = _PREV_TS.get(run_id) if run_id else None

    dt_prev_ms = out.pop("dt_prev_ms", None)
    if "timestamp" not in out:
        if prev_ts is not None and dt_prev_ms is not None:
            try:
                curr = prev_ts + timedelta(milliseconds=float(dt_prev_ms))
            except Exception:
                curr = datetime.now(timezone.utc)
        else:
            curr = datetime.now(timezone.utc)
        out["timestamp"] = curr.isoformat()

    # Update the tracker for the next event in this run.
    try:
        new_prev = datetime.fromisoformat(out["timestamp"])
        if run_id is not None:
            _PREV_TS[run_id] = new_prev
    except Exception:
        pass

    return out, prev_ts


def encode_event(evt: dict[str, Any], run_id: str | None = None) -> list[float]:
    """Encode a demo-friendly event dict into a 28-dim float list.

    Delegates to ``data.preprocessing.encode_event`` after key normalization.
    ``run_id`` is optional; when provided, it enables per-run dt_prev tracking.
    """
    canonical, prev_ts = _normalize_event(evt, run_id=run_id)
    vec = _canonical_encode_event(canonical, prev_timestamp=prev_ts)
    # Coerce any stray ints to floats so downstream consumers get a uniform dtype.
    return [float(x) for x in vec]


async def emit(run_id: str, evt: dict[str, Any], log_line: str) -> None:
    """POST one encoded event + log line to the control-plane /events endpoint.

    Swallows all network errors so behaviors can run in isolation.
    """
    vec = encode_event(evt, run_id=run_id)
    payload = {"run_id": run_id, "vec": vec, "log": log_line}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(f"{CONTROL_PLANE}/events", json=payload)
    except Exception:
        # Control-plane may be down during smoke tests — don't crash behaviors.
        pass


def reset_run(run_id: str) -> None:
    """Drop the prev-timestamp tracker for ``run_id`` (optional tidiness)."""
    _PREV_TS.pop(run_id, None)


# Small module-level signature info for humans reading the code:
__CANONICAL_ENCODER__ = "data.preprocessing.encode_event"
__DIMS__ = 28
