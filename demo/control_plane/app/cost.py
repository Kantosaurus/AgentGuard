"""In-memory monthly cost tracker for the LLM agent.

Pricing: defaults match MiniMax M2.7 list price ($0.80 / $1.20 per 1M tokens
input/output). Override with AGENT_INPUT_USD_PER_MTOK / AGENT_OUTPUT_USD_PER_MTOK.
Reset boundary: calendar month (UTC).
"""
from __future__ import annotations

import datetime as dt
import logging
import os

from .errors import MonthlyCapReached as _ErrMonthlyCapReached

# Re-export for tests:
MonthlyCapReached = _ErrMonthlyCapReached

log = logging.getLogger("agentguard.cost")


def _sonnet_cost_usd(*, input_tokens: int, output_tokens: int,
                     input_per_mtok: float, output_per_mtok: float) -> float:
    return (input_tokens / 1_000_000) * input_per_mtok \
         + (output_tokens / 1_000_000) * output_per_mtok


def _current_month_bucket() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")


class CostTracker:
    def __init__(self, *, cap_usd: float):
        self.cap_usd = cap_usd
        self.input_per_mtok = float(os.environ.get("AGENT_INPUT_USD_PER_MTOK", "0.80"))
        self.output_per_mtok = float(os.environ.get("AGENT_OUTPUT_USD_PER_MTOK", "1.20"))
        self._bucket = _current_month_bucket()
        self.month_total_usd = 0.0

    def _set_month_bucket(self, bucket: str) -> None:
        if bucket != self._bucket:
            self._bucket = bucket
            self.month_total_usd = 0.0

    def record(self, *, input_tokens: int, output_tokens: int) -> float:
        self._set_month_bucket(_current_month_bucket())
        cost = _sonnet_cost_usd(input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                input_per_mtok=self.input_per_mtok,
                                output_per_mtok=self.output_per_mtok)
        self.month_total_usd += cost
        log.info("usage delta_usd=%.4f month_total_usd=%.4f bucket=%s",
                 cost, self.month_total_usd, self._bucket)
        return cost

    def check(self) -> None:
        self._set_month_bucket(_current_month_bucket())
        if self.month_total_usd >= self.cap_usd:
            raise MonthlyCapReached(
                f"{self.month_total_usd:.2f} >= {self.cap_usd:.2f}"
            )
