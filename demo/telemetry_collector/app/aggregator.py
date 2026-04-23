"""Stream-1 aggregator — turns flat /proc samples into 32-dim feature vectors.

Canonical training-time aggregation:
    ``data.preprocessing.aggregate_telemetry_window`` + ``flatten_telemetry``
    (produces the 32-feature vector: 7 groups × {mean, max, min, std} = 28,
     plus syscall_entropy, unique_syscalls, total_syscalls, sample_count).

The training code consumes raw telemetry JSONL with nested keys like
``record["cpu"]["cpu_usage_pct"]``; the demo's /proc sampler emits flat keys
(``cpu_pct``, ``mem_pct``, ...). ``_to_training_record`` bridges that schema
so we call the *exact* training function and get byte-compatible windows.

Stream-1 features we cannot measure from /proc (dest_ip_entropy, syscall_entropy,
unique_syscalls, total_syscalls) are emitted as zero — the training schema allows
missing fields and the baseline-subtracted normalization makes zero a sensible
neutral value for idle workloads.

The 32-feature layout (STAT_GROUPS × {mean,max,min,std} ++ scalars) is:
    [0:4]   cpu {mean,max,min,std}
    [4:8]   memory
    [8:12]  processes
    [12:16] network_connections
    [16:20] dest_ip_entropy                (zeros — not sampled)
    [20:24] io_read_rate
    [24:28] io_write_rate
    [28]    syscall_entropy                (zero — not sampled)
    [29]    unique_syscalls                (zero — not sampled)
    [30]    total_syscalls                 (zero — not sampled)
    [31]    sample_count                   (number of /proc samples in this window)
"""
from __future__ import annotations

import sys
from collections import deque
from typing import Any, Deque, Optional

import numpy as np

# Main repo is mounted at /workspace inside the container and added to PYTHONPATH
# via the Dockerfile. The explicit sys.path.insert is a belt-and-braces guard so
# local pytest runs (outside the container) also resolve the import if the repo
# root is the working directory.
sys.path.insert(0, "/workspace")

from data.preprocessing import aggregate_telemetry_window, flatten_telemetry  # noqa: E402


def _to_training_record(sample: dict[str, Any]) -> dict[str, Any]:
    """Convert a flat /proc sample → the nested schema expected by training.

    Fields we can't measure from /proc are left absent; ``aggregate_telemetry_window``
    treats missing keys as zero via ``.get(..., 0)``.
    """
    return {
        "timestamp": sample.get("t", 0.0),
        "cpu": {"cpu_usage_pct": float(sample.get("cpu_pct", 0.0))},
        "memory": {"usage_pct": float(sample.get("mem_pct", 0.0))},
        "processes": {"count": int(sample.get("proc_count", 0))},
        "network": {
            "connection_count": int(sample.get("net_conn", 0)),
            # dest_ip_entropy is not sampled from /proc; leave at 0.
            "dest_ip_entropy": 0.0,
        },
        "file_io": {
            # The training aggregator uses "sectors_per_sec"; we pass raw byte
            # counters from /proc/<pid>/io. They flow through safe_stats the same
            # way so the relative statistics (mean/max/min/std across the window)
            # are still meaningful.
            "read_sectors_per_sec": float(sample.get("io_read", 0.0)),
            "write_sectors_per_sec": float(sample.get("io_write", 0.0)),
        },
        # syscalls are not sampled without an eBPF probe; the aggregator's
        # Counter/entropy math handles an empty dict cleanly.
        "syscalls": {"top_5": {}},
    }


def aggregate_stream1_window(samples: list[dict[str, Any]]) -> np.ndarray:
    """Aggregate a list of per-sample dicts into a 32-dim Stream-1 vector.

    Empty input yields a zero vector so callers don't need to branch.
    """
    if not samples:
        return np.zeros(32, dtype=np.float32)

    records = [_to_training_record(s) for s in samples]
    features = aggregate_telemetry_window(records)
    if features is None:
        return np.zeros(32, dtype=np.float32)
    vec = flatten_telemetry(features)
    return np.asarray(vec, dtype=np.float32)


class Aggregator:
    """Sliding-window Stream-1 aggregator backing the FastAPI service.

    Maintains a deque of the last ``seq_context`` aggregated windows, each a 32-dim
    vector, and exposes ``current_window()`` returning the ``(seq_context, 32)``
    float32 ndarray the control plane expects (zero-padded on the left until the
    buffer fills).

    Timing contract (matches ``main.py``):
        - Samples arrive at ~2 Hz via ``add(sample)``.
        - ``emit_window(now)`` is called every 5 s and builds one 30 s window.
        - The ``(8, 32)`` window returned by ``current_window()`` therefore covers
          roughly 8 × 5 s = 40 s of emit ticks, each summarising 30 s of samples.
    """

    def __init__(self, window_size: float = 30.0, seq_context: int = 8):
        self.window_size = float(window_size)
        self.seq_context = int(seq_context)
        self._samples: Deque[dict[str, Any]] = deque()
        self._windows: Deque[np.ndarray] = deque(maxlen=self.seq_context)

    def add(self, sample: dict[str, Any]) -> None:
        """Append a sample and evict anything older than the full context."""
        self._samples.append(sample)
        # Keep enough samples to span the entire sliding context even if emit_window
        # has not yet drained them — prevents the deque from growing without bound.
        horizon = self.seq_context * self.window_size
        cutoff = float(sample.get("t", 0.0)) - horizon
        while self._samples and float(self._samples[0].get("t", 0.0)) < cutoff:
            self._samples.popleft()

    def emit_window(self, now: float) -> Optional[np.ndarray]:
        """Build one 32-dim feature vector for the ``[now - window_size, now]`` window.

        Returns the vector (and pushes it onto the sliding buffer) if at least one
        sample falls inside, otherwise ``None``.
        """
        start = now - self.window_size
        in_window = [
            s for s in self._samples if start <= float(s.get("t", 0.0)) <= now
        ]
        if not in_window:
            return None
        vec = aggregate_stream1_window(in_window)
        self._windows.append(vec)
        return vec

    def current_window(self) -> np.ndarray:
        """Return the ``(seq_context, 32)`` sliding tensor, left-zero-padded.

        When fewer than ``seq_context`` windows have been emitted, missing slots
        are filled with zero vectors at the *front* (oldest side) so the most
        recent emitted window is always at index ``seq_context - 1``.
        """
        pad = self.seq_context - len(self._windows)
        zeros = [np.zeros(32, dtype=np.float32)] * max(pad, 0)
        stacked = zeros + list(self._windows)
        return np.stack(stacked, axis=0).astype(np.float32, copy=False)
