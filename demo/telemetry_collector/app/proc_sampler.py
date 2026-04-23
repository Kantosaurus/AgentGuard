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


def _read_stat_fields(pid: int) -> list[str] | None:
    """Return the whitespace-split /proc/<pid>/stat fields starting from ``state``.

    The ``comm`` field may contain spaces and parens, so we rsplit on the final
    ") " to isolate the rest of the line; ``fields[0]`` is then ``state``.
    Returns ``None`` if the PID has vanished or stat is unreadable.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, PermissionError):
        return None
    try:
        return stat.rsplit(") ", 1)[1].split()
    except IndexError:
        return None


def _pid_ppid(pid: int) -> int:
    """Parent PID (0 if unreadable or root)."""
    f = _read_stat_fields(pid)
    if f is None or len(f) < 2:
        return 0
    try:
        return int(f[1])   # fields[0]=state, fields[1]=ppid
    except ValueError:
        return 0


def _pid_tree(root: int) -> list[int]:
    """BFS the descendants of ``root`` and return [root, child, grandchild, ...].

    stress-ng and any other subprocess the worker spawns shows up as a child of
    the worker's uvicorn PID; we need to sum their CPU to see real resource
    usage. Scanning /proc is O(num_pids) but only runs at 2 Hz so it's fine.
    """
    children: dict[int, list[int]] = {}
    try:
        all_pids = [int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()]
    except (FileNotFoundError, PermissionError):
        return [root]
    for pid in all_pids:
        ppid = _pid_ppid(pid)
        if ppid > 0:
            children.setdefault(ppid, []).append(pid)

    tree = [root]
    frontier = [root]
    while frontier:
        nxt = []
        for p in frontier:
            for c in children.get(p, []):
                tree.append(c)
                nxt.append(c)
        frontier = nxt
    return tree


def _pid_utime_stime(pid: int) -> float:
    """utime + stime for ``pid`` alone, in jiffies. Returns 0.0 if PID vanished."""
    f = _read_stat_fields(pid)
    if f is None:
        return 0.0
    try:
        utime, stime = int(f[11]), int(f[12])
        return float(utime + stime)
    except (IndexError, ValueError):
        return 0.0


def _pid_tree_utime_stime(root: int) -> float:
    """Sum of utime+stime across ``root`` and all its descendant processes.

    Needed because uvicorn (the container's PID 1) spawns subprocesses like
    stress-ng whose CPU doesn't show up in the root's own stat.
    """
    return sum(_pid_utime_stime(p) for p in _pid_tree(root))


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
    proc_cpu = _pid_tree_utime_stime(pid)
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
