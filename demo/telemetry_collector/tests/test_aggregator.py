"""Shape/value tests for the Stream-1 sliding aggregator."""
import time

import numpy as np
import pytest

from app.aggregator import Aggregator, aggregate_stream1_window


def _sample(t: float, **over: float) -> dict:
    """Build a flat /proc-style sample with sensible defaults, override per test."""
    base = {
        "t": t,
        "cpu_pct": 10.0,
        "mem_pct": 50.0,
        "proc_count": 100,
        "net_conn": 5,
        "io_read": 0.0,
        "io_write": 0.0,
    }
    base.update(over)
    return base


def test_aggregate_stream1_window_shape():
    """Direct aggregation helper returns a length-32 float32 vector."""
    t0 = time.time()
    samples = [_sample(t0 + i * 0.5) for i in range(60)]
    vec = aggregate_stream1_window(samples)
    assert vec.shape == (32,)
    assert vec.dtype == np.float32


def test_aggregate_empty_returns_zeros():
    vec = aggregate_stream1_window([])
    assert vec.shape == (32,)
    assert np.all(vec == 0.0)


def test_current_window_zero_padded_before_fill():
    """Fresh aggregator with no emits returns an (8, 32) zero matrix."""
    a = Aggregator(window_size=30.0, seq_context=8)
    w = a.current_window()
    assert w.shape == (8, 32)
    assert np.all(w == 0.0)


def test_sliding_window_fills_to_eight_windows():
    """Feeding 8 * 30 s = 240 s of samples and emitting each 30 s fills the buffer."""
    a = Aggregator(window_size=30.0, seq_context=8)
    t0 = time.time()
    # Feed 2 Hz samples across 240 s.
    for i in range(8 * 60):
        a.add(_sample(t0 + i * 0.5))
    # Emit one window per 30 s boundary.
    for k in range(1, 9):
        now = t0 + k * 30.0
        out = a.emit_window(now)
        assert out is not None
        assert out.shape == (32,)

    w = a.current_window()
    assert w.shape == (8, 32)
    # Any completely-zero row would indicate a padding bug at full fill.
    row_sums = w.sum(axis=1)
    assert np.all(row_sums > 0), f"expected every slot populated, got row sums {row_sums}"


def test_cpu_stats_reflect_input():
    """cpu.mean and cpu.max should surface the actual sample values."""
    a = Aggregator(window_size=30.0, seq_context=8)
    t0 = time.time()
    for i in range(60):
        a.add(_sample(t0 + i * 0.5, cpu_pct=42.0))
    out = a.emit_window(t0 + 30.0)
    assert out is not None
    # Layout: [0:4] cpu {mean, max, min, std}
    assert out[0] == pytest.approx(42.0)
    assert out[1] == pytest.approx(42.0)
    assert out[2] == pytest.approx(42.0)
    assert out[3] == pytest.approx(0.0)  # no variance for constant input


def test_emit_window_no_samples_returns_none():
    a = Aggregator(window_size=30.0, seq_context=8)
    assert a.emit_window(time.time()) is None


def test_sample_count_tracked_in_last_feature():
    """Feature [31] is the raw sample_count for the window."""
    a = Aggregator(window_size=30.0, seq_context=8)
    t0 = time.time()
    for i in range(20):
        a.add(_sample(t0 + i * 0.5))
    out = a.emit_window(t0 + 30.0)
    assert out is not None
    assert out[31] == pytest.approx(20.0)
