"""Unit tests for Stream1Buffer and Stream2Buffer."""
from __future__ import annotations

import numpy as np
import pytest

from app.buffers import Stream1Buffer, Stream2Buffer


def test_s1_preseeded_from_baseline():
    base = np.arange(8 * 32, dtype=np.float32).reshape(8, 32)
    buf = Stream1Buffer.from_baseline(base)

    assert buf.current().shape == (8, 32)
    assert np.allclose(buf.current(), base)


def test_s1_push_rotates_rows():
    base = np.arange(8 * 32, dtype=np.float32).reshape(8, 32)
    buf = Stream1Buffer.from_baseline(base)

    new = np.full(32, 99.0, dtype=np.float32)
    buf.push(new)
    cur = buf.current()

    assert np.allclose(cur[-1], 99.0)
    # Oldest row (originally row 0) should have fallen out; new row 0 was row 1.
    assert np.allclose(cur[0], base[1])


def test_s1_push_wrong_shape_raises():
    buf = Stream1Buffer()
    with pytest.raises(ValueError):
        buf.push(np.zeros(10, dtype=np.float32))


def test_s1_from_baseline_rejects_non_2d():
    with pytest.raises(ValueError):
        Stream1Buffer.from_baseline(np.zeros(32, dtype=np.float32))


def test_s2_empty_has_all_false_mask():
    buf = Stream2Buffer(max_len=64, dim=28)
    seq, mask = buf.current()

    assert seq.shape == (64, 28)
    assert mask.shape == (64,)
    assert not mask.any()


def test_s2_push_fills_tail_and_marks_mask():
    buf = Stream2Buffer(max_len=64, dim=28)
    buf.push(np.ones(28, dtype=np.float32))
    seq, mask = buf.current()

    assert mask[-1]
    assert not mask[-2]
    assert np.allclose(seq[-1], 1.0)
    assert np.allclose(seq[-2], 0.0)


def test_s2_ring_caps_at_max_len():
    buf = Stream2Buffer(max_len=4, dim=28)
    for i in range(10):
        v = np.full(28, float(i), dtype=np.float32)
        buf.push(v)
    seq, mask = buf.current()

    assert mask.all()
    assert np.allclose(seq[-1], 9.0)
    assert np.allclose(seq[0], 6.0)  # oldest surviving


def test_s2_push_wrong_shape_raises():
    buf = Stream2Buffer()
    with pytest.raises(ValueError):
        buf.push(np.zeros(10, dtype=np.float32))
