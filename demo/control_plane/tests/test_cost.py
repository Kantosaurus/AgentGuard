from __future__ import annotations

import pytest

from app.cost import CostTracker, MonthlyCapReached, _sonnet_cost_usd
from app.errors import MonthlyCapReached as _ErrMonthlyCapReached


def test_cost_estimate_known_pricing():
    # MiniMax pricing knob defaults to $0.80 input / $1.20 output per 1M.
    cost = _sonnet_cost_usd(input_tokens=1_000_000, output_tokens=0,
                            input_per_mtok=0.80, output_per_mtok=1.20)
    assert abs(cost - 0.80) < 1e-6


def test_tracker_accumulates_within_month(monkeypatch):
    t = CostTracker(cap_usd=100.0)
    t.record(input_tokens=100_000, output_tokens=50_000)
    assert t.month_total_usd > 0
    t.record(input_tokens=100_000, output_tokens=50_000)
    assert t.month_total_usd >= 2 * (100_000 * 0.80 / 1_000_000
                                     + 50_000 * 1.20 / 1_000_000)


def test_tracker_resets_on_new_month(monkeypatch):
    # Freeze "now" inside cost.py so record() doesn't auto-roll the bucket
    # while the test is exercising the reset logic.
    import app.cost as _cost
    monkeypatch.setattr(_cost, "_current_month_bucket", lambda: "2026-04")
    t = CostTracker(cap_usd=100.0)
    t._set_month_bucket("2026-04")
    t.record(input_tokens=10_000_000, output_tokens=10_000_000)
    over = t.month_total_usd
    t._set_month_bucket("2026-05")
    assert t.month_total_usd == 0
    assert over > 0


def test_check_caps_raises_when_exceeded():
    t = CostTracker(cap_usd=0.001)
    t.record(input_tokens=10_000, output_tokens=10_000)
    with pytest.raises(MonthlyCapReached):
        t.check()


def test_monthly_cap_reached_is_alias_of_error():
    assert MonthlyCapReached is _ErrMonthlyCapReached
