"""One-shot /proc scraper.

Works against either the host PID or a PID visible inside the container (the
control-plane passes the target worker's host PID on startup via POST /target/{pid}).

All reads are tolerant: if a particular /proc entry is unreadable (PermissionError
or FileNotFoundError, which happens when the PID exits between reads), we fall back
to zeros for that field rather than raising so the sampling loop stays alive.

The returned dict matches the field names expected by ``aggregator.py``:
    t, cpu_pct, mem_pct, proc_count, net_conn, io_read, io_write
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Sample:
    t: float
    cpu_pct: float
    mem_pct: float
    proc_count: int
    net_conn: int
    io_read: float
    io_write: float


# Per-PID running totals used to turn cumulative CPU ticks into a percentage.
_PREV_CPU: dict[int, tuple[float, float]] = {}


def _proc_stat_total() -> float:
    """Sum of all jiffies across all modes from the first ``cpu`` line in /proc/stat."""
    try:
        parts = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
        return float(sum(int(x) for x in parts))
    except (FileNotFoundError, PermissionError, ValueError):
        return 0.0


def _pid_utime_stime(pid: int) -> float:
    """utime + stime for ``pid`` in jiffies. Returns 0.0 if the PID vanished."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, PermissionError):
        return 0.0
    # /proc/<pid>/stat format: "pid (comm with spaces) state ppid ...".
    # rsplit on ") " once so process names containing spaces don't shift fields.
    try:
        fields = stat.rsplit(") ", 1)[1].split()
        utime, stime = int(fields[11]), int(fields[12])
        return float(utime + stime)
    except (IndexError, ValueError):
        return 0.0


def _mem_pct() -> float:
    """Percent of MemTotal currently in use (1 - MemAvailable/MemTotal)."""
    try:
        lines = dict(
            l.split(":", 1)
            for l in Path("/proc/meminfo").read_text().splitlines()
            if ":" in l
        )
        total = int(lines["MemTotal"].strip().split()[0])
        avail = int(lines["MemAvailable"].strip().split()[0])
        if total <= 0:
            return 0.0
        return 100.0 * (1.0 - avail / total)
    except (FileNotFoundError, PermissionError, KeyError, ValueError):
        return 0.0


def _net_tcp_count() -> int:
    """Number of TCP sockets on the host (header-line subtracted)."""
    try:
        return max(0, len(Path("/proc/net/tcp").read_text().splitlines()) - 1)
    except (FileNotFoundError, PermissionError):
        return 0


def _io_bytes(pid: int) -> tuple[float, float]:
    """(read_bytes, write_bytes) from /proc/<pid>/io. Returns zeros if inaccessible.

    Note that /proc/<pid>/io is protected on many kernels; reading another process's
    io counters typically requires CAP_SYS_PTRACE or matching uid.
    """
    try:
        lines = Path(f"/proc/{pid}/io").read_text().splitlines()
    except (FileNotFoundError, PermissionError):
        return 0.0, 0.0
    vals: dict[str, str] = {}
    for line in lines:
        if ": " in line:
            k, v = line.split(": ", 1)
            vals[k] = v
    try:
        return float(vals.get("read_bytes", "0")), float(vals.get("write_bytes", "0"))
    except ValueError:
        return 0.0, 0.0


def _proc_count() -> int:
    """Number of PIDs visible in /proc. Falls back to 0 if /proc is unavailable."""
    try:
        return sum(1 for p in Path("/proc").iterdir() if p.name.isdigit())
    except (FileNotFoundError, PermissionError):
        return 0


def sample_once(pid: int) -> dict[str, Any]:
    """One-shot read of /proc state for the given PID.

    The CPU percentage is computed against the previous call for the same PID; the
    very first call returns ``cpu_pct=0.0`` because we have no delta yet. Subsequent
    calls produce the standard process-share-of-CPU metric:

        cpu_pct = 100 * Δ(utime + stime) / Δ(total jiffies)
    """
    now = time.time()
    proc_cpu = _pid_utime_stime(pid)
    sys_cpu = _proc_stat_total()
    prev = _PREV_CPU.get(pid)
    _PREV_CPU[pid] = (proc_cpu, sys_cpu)

    if prev is None:
        cpu_pct = 0.0
    else:
        dp, ds = proc_cpu - prev[0], sys_cpu - prev[1]
        cpu_pct = 100.0 * (dp / ds) if ds > 0 else 0.0

    r, w = _io_bytes(pid)
    return asdict(
        Sample(
            t=now,
            cpu_pct=float(cpu_pct),
            mem_pct=float(_mem_pct()),
            proc_count=int(_proc_count()),
            net_conn=int(_net_tcp_count()),
            io_read=float(r),
            io_write=float(w),
        )
    )
