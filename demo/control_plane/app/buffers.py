"""Per-run ring buffers for Stream 1 (8x32 sliding telemetry windows) and
Stream 2 (64-event ring of 28-dim action embeddings plus a valid mask).

The control plane keeps one instance of each buffer alive for the duration of
a single run. Stream 1 is pre-seeded from the idle baseline so the model sees
a full context window from tick #1; Stream 2 starts empty and is filled as
action events arrive from the agent worker.
"""
from __future__ import annotations

from collections import deque
from typing import Tuple

import numpy as np


class Stream1Buffer:
    """Fixed-length deque of 32-dim Stream-1 feature rows (newest at the right)."""

    def __init__(self, seq_context: int = 8, dim: int = 32):
        self._seq_context = seq_context
        self._dim = dim
        self._buf: "deque[np.ndarray]" = deque(maxlen=seq_context)

    @classmethod
    def from_baseline(cls, baseline: np.ndarray) -> "Stream1Buffer":
        """Construct a buffer pre-seeded with ``baseline`` (shape (seq, dim))."""
        if baseline.ndim != 2:
            raise ValueError(
                f"baseline must be 2D, got shape {baseline.shape}"
            )
        seq_context, dim = baseline.shape
        b = cls(seq_context=seq_context, dim=dim)
        for row in baseline:
            b._buf.append(row.astype(np.float32, copy=True))
        return b

    def push(self, vec: np.ndarray) -> None:
        if vec.shape != (self._dim,):
            raise ValueError(
                f"expected shape ({self._dim},), got {vec.shape}"
            )
        self._buf.append(vec.astype(np.float32, copy=True))

    def current(self) -> np.ndarray:
        """Return the (seq_context, dim) ndarray; zero-pads on the left if not full."""
        n = len(self._buf)
        if n == self._seq_context:
            return np.stack(list(self._buf), axis=0)
        out = np.zeros((self._seq_context, self._dim), dtype=np.float32)
        if n > 0:
            out[self._seq_context - n :] = np.stack(list(self._buf), axis=0)
        return out


class Stream2Buffer:
    """Ring of up to ``max_len`` 28-dim event embeddings with a validity mask.

    The model expects a left-padded sequence (oldest first, padding on the
    left, most recent event at the right), so we lay out both ``seq`` and
    ``mask`` that way.
    """

    def __init__(self, max_len: int = 64, dim: int = 28):
        self._max = max_len
        self._dim = dim
        self._events: "deque[np.ndarray]" = deque(maxlen=max_len)

    def push(self, event_vec: np.ndarray) -> None:
        if event_vec.shape != (self._dim,):
            raise ValueError(
                f"expected shape ({self._dim},), got {event_vec.shape}"
            )
        self._events.append(event_vec.astype(np.float32, copy=True))

    def current(self) -> Tuple[np.ndarray, np.ndarray]:
        n = len(self._events)
        seq = np.zeros((self._max, self._dim), dtype=np.float32)
        mask = np.zeros(self._max, dtype=bool)
        if n > 0:
            seq[self._max - n :] = np.stack(list(self._events), axis=0)
            mask[self._max - n :] = True
        return seq, mask

    def __len__(self) -> int:
        return len(self._events)
