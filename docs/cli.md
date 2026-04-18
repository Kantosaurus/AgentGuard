# CLI reference

Every entry-point the repository ships. Pair this page with
[`configuration.md`](./configuration.md) for the YAML keys each consumes.

---

## 1. `main.py`

```
python main.py --mode {preprocess,train,eval,cv,test} \
               [--config PATH]       # default: config.yml
               [--weights_config PATH]  # required for --mode test
```

| Mode | What it does | Outputs |
|---|---|---|
| `preprocess` | JSONL → per-agent `.pt` tensors. | `data/processed/{agent}.pt` |
| `train` | Fit on `data.train_agents`, validate on `data.val_agents`, checkpoint best AUROC. | `data/processed/checkpoints/best_model.pt`, `logs/train_*.log`, `logs/train_*_epochs.csv` |
| `eval` | Load best checkpoint → score on `data.test_agents`. | stdout + log, no new file |
| `cv` | 5-fold stratified agent-level CV. | `data/processed/checkpoints/best_model_fold{1..5}.pt`, per-fold logs |
| `test` | External inference mode; writes per-agent Markdown report. | `results.md` |

Required config shape differs per mode; `--mode test` needs
`inference.checkpoint_path` (and a matching `--weights_config`).

---

## 2. Sweep

```
python -m sweep.run_sweep --phase {1,2,3,4,all}
                          [--n-trials N]
                          [--config PATH]

python -m sweep.analysis --phase {1,2,3,all}

python -m sweep.ensemble --top-k K [--config PATH]
```

Storage: `sweep/results/optuna.db` by default; override with
`OPTUNA_STORAGE=postgresql://...`.

Produces: `sweep/results/best_params_phase{N}.json`,
`trials_phase{N}.csv`, `phase4_results.json` (Phase 4 only).

---

## 3. Apply sweep best params

```
python -m utils.apply_best_params
```

Reads every `sweep/results/best_params_phase{1..4}.json` and writes
`config_best.yml` at the repo root.

---

## 4. Baselines

```
python baselines/run_baselines.py --config config_best.yml \
                                  [--seeds 42,1337,2024]   # default: 42,1337,2024
                                  [--fast]                 # 3 epochs / model
                                  [--out results/baselines.csv]   # default
```

Runs five baselines (IsolationForest / LSTMAE / CNNAE / TransformerAE /
DeepSVDD) across `seeds × k_folds`. Writes CSV + Markdown + per-(baseline,
seed, fold) prediction NPZs under `predictions/`.

---

## 5. Multi-seed training

```
python scripts/train_multiseed.py --config config_best.yml \
                                  [--seeds 42,1337,2024]
                                  [--folds 1,2,3]          # default: all
                                  [--fast]                 # 5 epochs/patience
                                  [--epochs N]             # override both epochs and patience
                                  [--out_dir DIR]          # default: cwd
```

Per (seed, fold), outputs:

- `logs/seed{S}_fold{F}_epochs.csv`
- `data/processed/checkpoints/model_seed{S}_fold{F}.pt`
- `predictions/agentguard_seed{S}_fold{F}.npz`
- `latents/agentguard_seed{S}_fold{F}.npz`

---

## 6. Single-fold orchestration helper

```
python scripts/run_fold.py --config-json  /tmp/config.json \
                           --train-agents agent-1,agent-2,... \
                           --val-agents   agent-3,... \
                           --test-agents  agent-4,... \
                           --out-json     /tmp/metrics.json \
                           --checkpoint-suffix notebook_job0
```

Designed to be spawned as a subprocess from a notebook orchestrator;
`CUDA_VISIBLE_DEVICES` pins each to one GPU.

---

## 7. Interpretability reports

```
python scripts/generate_interpretability_reports.py \
    --config PATH           # default: config_best.yml
    --seed N                # default: 42
    --fold N                # default: 1
    --out_dir DIR           # default: results/reports
    --n_per_category N      # default: 3
    --ig_steps N            # default: 50
```

Needs `data/processed/checkpoints/model_seed{seed}_fold{fold}.pt`; falls
back to a random-init stub with a warning if absent.

---

## 8. Dashboard

```
streamlit run dashboard.py
```

SSH credentials (host/port/user/key) are configured in the sidebar.
Expects the target host to have `/var/log/agentguard/telemetry/` and
`actions/` under the paths configured at the top of `dashboard.py`.

---

## 9. Server-side action logger

```
# Log a test heartbeat event
python action_collector.py --mode log

# Execute a prompt and log the event (blocking)
echo "your prompt here" | python action_collector.py --mode exec
```

Integrates with an agent framework via:

```python
from action_collector import log_action_event, AgentGuardOpenClawHook
hook = AgentGuardOpenClawHook()
# attach hook.on_tool_call / on_tool_result / on_llm_response / on_user_message
```

---

## 10. Full pipeline (GPU cluster)

```
bash scripts/run_full_pipeline.sh               # full 4-stage pipeline
bash scripts/run_full_pipeline.sh --smoke-only  # stage 4 smoke test only
bash scripts/run_full_pipeline.sh --skip-deps   # skip apt + pip install
bash scripts/run_full_pipeline.sh --skip-smoke  # skip the 1-fold smoke test
bash scripts/run_full_pipeline.sh --gpus 4      # cap Stage 1 fan-out
```

Stages: deps → CUDA verify → smoke → Stage 1 (multi-seed training in
parallel) → Stage 2 (baselines × 3 seeds) → Stage 3 (plots) → Stage 4
(interpretability reports).

Artifacts:

- `logs/pipeline_*.log` — master log (tee'd)
- `logs/seed*_fold*_epochs.csv` — per-run epoch CSVs
- `data/processed/checkpoints/model_seed*_fold*.pt` — per-run checkpoints
- `predictions/` + `latents/` — per-run NPZ dumps
- `results/figures/*.pdf` — plots
- `results/reports/**/*.md` — interpretability reports

---

## 11. Smoke tests

```
python -m tests.phase_b_smoke
```

Exercises cross-attention and gated fusion forward passes, asserts
attention shapes, verifies masked-key attention ≈ 0, and the non-
cross-attention path returns the expected keys.

---

## 12. Convenience shell scripts

| Script | Purpose |
|---|---|
| `scripts/train_cv.sh` | One-liner wrapping `python main.py --mode cv --config config_best.yml` |
| `scripts/train_fixed_split.sh` | One-liner for `--mode train --config config_best.yml` |
| `scripts/optuna_train_cv.sh` | Run Phase 2+3 with 3-fold CV (legacy) |
| `scripts/run_full_pipeline.sh` | See §10 |
| `scripts/clean.py` | Prune old checkpoints / logs |
