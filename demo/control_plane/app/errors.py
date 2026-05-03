"""Domain exceptions translated to HTTP errors at the FastAPI boundary."""
from __future__ import annotations


class RunBusy(Exception):
    """Raised when a run is already in progress (single-tenant mutex)."""
    def __init__(self, retry_after_sec: int) -> None:
        super().__init__("run already in progress")
        self.retry_after_sec = retry_after_sec
