# Deployment & operations

How to run AgentGuard in live inference, how the dashboard fits in, and
what the operational surface looks like.

---

## 1. Deployment topology

```
┌──────────────────────────────────────────────────────────────┐
│                     Agent host (Linux)                        │
│                                                               │
│  ┌───────────────────┐      ┌──────────────────────────┐     │
│  │ Agent container 1 │      │ telemetry_collector.py   │     │
│  │  agent_server.py  │──┬──▶│  every 5s → JSONL        │     │
│  │  action_collector │  │   └──────────────────────────┘     │
│  └───────────────────┘  │                                     │
│          ...            │   /var/log/agentguard/              │
│  ┌───────────────────┐  │     ├── agent-N/telemetry/*.jsonl   │
│  │ Agent container N │──┘     └── agent-N/actions/*.jsonl     │
│  │  agent_server.py  │                                         │
│  └───────────────────┘                                         │
│                                                               │
│  (Optional) inference service:                                │
│    python main.py --mode test → score per window              │
└──────────────────────────────────────────────────────────────┘
                             ▲
                             │ SSH/SFTP (paramiko)
                             │
                ┌───────────────────────────┐
                │ Operator workstation      │
                │                           │
                │  streamlit run dashboard  │
                │   - tails JSONL           │
                │   - runs model inference  │
                │   - shows live score      │
                └───────────────────────────┘
```

---

## 2. Inference serving patterns

### 2.1 Dashboard (current)

`dashboard.py` is the simplest supported pattern: operator's machine
opens an SSH session to the agent host, paramiko tails the JSONL files,
and model inference runs locally with a checkpoint loaded at startup.

Pros:
- No code on the agent host beyond the collectors and agents themselves.
- Single-user, easy to reason about.
- Model stays on the operator's hardware (no GPU needed on the server).

Cons:
- One consumer at a time.
- No historical querying (lives in RAM).
- SSH latency matters — poll interval 1 s.

### 2.2 On-host inference (future)

For continuous monitoring with alerting, run the model directly on the
agent host (or a nearby compute node) and emit scores to a time-series
database. Skeleton:

```python
# pseudo-code — not shipped yet
model = AgentGuardModel(...)
model.load_state_dict(torch.load("best_model.pt")["model_state_dict"])
model.eval()

for window in stream_windows():  # 30-s aligned, emitted by the aggregator
    stream1 = prepare_stream1(window)        # [1, 8, 32]
    stream2_seq, mask = prepare_stream2(window)   # [1, 64, 28] + [1, 64]
    with torch.no_grad():
        score = model(stream1, stream2_seq, mask)["anomaly_score"].item()
    emit_metric("agentguard.score", score, agent_id=window.agent_id)
    if score > THRESHOLD:
        fire_alert(window)
```

Depends on:

- A matching preprocessing pipeline on-host (ideally the same
  `data.preprocessing` module, not a re-implementation).
- A validation-set-tuned threshold (see
  [`evaluation.md §2`](./evaluation.md#2-threshold-selection)).

---

## 3. SSH / file-system contract

The dashboard and the `--mode test` pipeline both assume:

- `TELEMETRY_LOG_DIR = /var/log/agentguard/telemetry` (or configurable in
  the dashboard script).
- `ACTIONS_LOG_DIR = /var/log/agentguard/actions`.
- Per-agent subdirectories: `agent-{1..20}/`.
- Daily JSONL files: `{agent}/{telemetry|actions}/{YYYY-MM-DD}.jsonl`.

The collectors are expected to append, not rotate mid-day, so the
dashboard can keep a file handle open and poll for new lines.

---

## 4. Model checkpoint compatibility

A checkpoint is tied to the architecture that produced it. To load a
checkpoint successfully:

1. `build_model(config)` must produce a model with identical parameter
   names and shapes as the one saved.
2. `config.model.*` must match the training-time values. `main.py --mode
   test` takes `--weights_config` separately from `--config` specifically
   to decouple "what data to score" from "what model shape".

Worst-case recovery: `torch.load(ckpt, map_location="cpu")` and inspect
`list(ckpt["model_state_dict"].keys())` to reverse-engineer the shape.

---

## 5. GPU considerations

- **CUDA 12.4** tested. CUDA 11.8 should work but is not validated.
- **TF32 disabled** in `set_global_seed` because Hopper H100/H200 TF32
  can push the SSM prefix-scan into NaN → BCELoss assertion → process
  death. Throughput cost is minor.
- **Multi-GPU via DataParallel** is not implemented. Parallelism is at
  the fold/seed level (`parallel -j N` in `run_full_pipeline.sh`). For a
  larger model or larger dataset, wrap in `DistributedDataParallel`
  manually.

---

## 6. Reproducibility across hosts

Expected:

- Same PyTorch major version.
- Same CUDA major version.
- Same preprocessed `.pt` files (hash-verify if cross-host).
- Same seed (the default `set_global_seed(42)` is called at the top of
  every CLI entry point).

Not expected:

- Bit-for-bit equivalence across GPU generations. cuBLAS/cuDNN algorithm
  selection differs. Mean metrics across seeds are stable to ~0.01 AUROC.

---

## 7. Alerting guidance

Don't threshold the raw sigmoid score directly in production:

1. **Score smoothing** — a 3-window rolling mean greatly reduces
   false-positive flare from isolated bursty windows.
2. **Persistence rule** — require score > T for K consecutive windows
   (e.g. 3 windows × 30 s = 90 s of sustained elevation) before firing.
3. **Rate limiting** — deduplicate alerts per (agent, attack_category,
   rolling window) to avoid alert fatigue during a single attack.
4. **Human-in-the-loop review** — every firing should auto-generate an
   interpretability report via
   `scripts/generate_interpretability_reports.py` and attach it to the
   alert.

Threshold `T` should come from the val set, not test:

```python
thr = pick_threshold(val_scores, val_labels)
```

Re-tune threshold when any of the following change: model, attack
distribution in training, normal workload in the field.

---

## 8. Data retention & privacy

Collectors log:

- **Stream 1**: numeric only, no strings. Safe to retain indefinitely.
- **Stream 2**: `tokens_in`/`tokens_out` counts, latency, tool name,
  source label. **Args hashes** are logged, not argument content, so
  PII / secrets in tool calls don't leak to the JSONL — but verify your
  `action_collector` integration doesn't accidentally log raw arguments
  via `extra={}`.
- **LLM responses**: full response string may be retained by your
  agent's own logging; not required by AgentGuard. Redact before
  ingesting if retention is a concern.

The attack manifests `attacks-*.jsonl` do carry the raw prompt strings —
keep them alongside the raw data only in training environments, not in
production log aggregation.

---

## 9. Security hardening of the collectors

- The collector runs inside each agent container with access to
  `/proc/*`. On a shared kernel (Docker), syscall visibility is roughly
  per-container; in a kubernetes multi-tenant context, check that the
  Pod's `procMount` is `Default` (not `Unmasked`).
- The dashboard SSHes into the agent host as root in the default sample.
  Create a dedicated read-only user with access to
  `/var/log/agentguard/*` and nothing else for production use.
- The `exec_prompt` entry point in `action_collector.py` is **intended
  only for development / demo** — it forwards arbitrary stdin to the
  agent. Do not expose it to untrusted operators.

---

## 10. Failure isolation

| Failure | Blast radius | Containment |
|---|---|---|
| Dashboard crash | operator only | restart streamlit |
| Collector missing JSONL entries | that agent only | preprocessing backfills from union of Stream 1 + Stream 2 windows — model degrades gracefully |
| Model NaN on a window | that window only | BCE NaN guard → score=0.5 for that sample, trainer continues |
| Agent exfil succeeds during detection | that agent only | model flags the window after-the-fact; sequel events get elevated scores from attention bleed |
| SSH timeout | dashboard only | paramiko reconnect loop in the dashboard's polling thread |

See [`troubleshooting.md`](./troubleshooting.md) for recovery recipes.

---

## 11. Ops runbook skeleton

1. **Confirm preprocessed data is current** —
   `ls -lt data/processed/*.pt | head`; each agent should have a `.pt`
   more recent than today's JSONL.
2. **Smoke-test the model** —
   `python -m tests.phase_b_smoke` (seconds).
3. **Start dashboard** — `streamlit run dashboard.py`, fill SSH creds in
   the sidebar.
4. **Verify live inference** — top-right panel shows a non-NaN score
   within 30 s of the first collected window.
5. **If scores are elevated** — run
   `scripts/generate_interpretability_reports.py --config config_best.yml --seed 42 --fold F`
   with the fold that covers that agent and inspect the attribution
   heatmap before declaring an incident.

---

## 12. Scaling notes

- **More agents** — `make_stratified_folds` assumes the 15/5 split; the
  tier tranches (5/3/7) are hard-coded. Adjust `make_stratified_folds`
  for different population sizes.
- **Longer traces** — `seq_context > 16` hasn't been evaluated; Mamba
  scales linearly but you'll re-validate loss weights.
- **More tool classes** — `data/preprocessing.py::KNOWN_TOOLS` has 6
  hand-chosen tools; novel tools go into one of 10 hash buckets. For a
  much wider tool surface, expand `NUM_TOOL_SLOTS` and re-preprocess.
