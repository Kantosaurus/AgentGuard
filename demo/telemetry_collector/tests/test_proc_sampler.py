"""Sanity checks for the /proc sampler.

These tests assume they run on a Linux host (or inside a Linux container) that has
/proc mounted — which is how CI and the Docker test target are configured.
"""
import os
import time

import pytest

from app.proc_sampler import sample_once


REQUIRED_KEYS = {"t", "cpu_pct", "mem_pct", "proc_count", "net_conn", "io_read", "io_write"}


def test_sample_fields_present():
    """First sample must contain every declared field and only numeric values."""
    s = sample_once(pid=os.getpid())
    assert set(s) >= REQUIRED_KEYS
    for k, v in s.items():
        assert isinstance(v, (int, float)), f"{k}={v!r} is {type(v)}, expected numeric"


def test_sample_values_nonnegative():
    """Everything that's a fraction/count must be >= 0 (t is a wall-clock stamp)."""
    s = sample_once(pid=os.getpid())
    for k in ("cpu_pct", "mem_pct", "proc_count", "net_conn", "io_read", "io_write"):
        assert s[k] >= 0, f"{k}={s[k]} should be non-negative"


def test_cpu_pct_finite_across_two_samples():
    """Second sample sees a populated delta and returns a finite cpu_pct."""
    sample_once(pid=os.getpid())  # prime the previous-tick cache
    # Burn a little CPU so the delta is nontrivial.
    deadline = time.time() + 0.05
    while time.time() < deadline:
        _ = sum(i * i for i in range(1000))
    s2 = sample_once(pid=os.getpid())
    assert 0.0 <= s2["cpu_pct"] <= 100.0 * os.cpu_count()  # hard upper bound


def test_sample_vanished_pid_returns_zeros():
    """If the PID does not exist, we must still return a well-formed dict."""
    # PID 2**22 is effectively unused on any real system.
    s = sample_once(pid=2**22)
    assert set(s) >= REQUIRED_KEYS
    assert s["cpu_pct"] == 0.0
    assert s["io_read"] == 0.0
    assert s["io_write"] == 0.0
