# Training

Everything under [`training/`](../training) plus the cross-validation and
multi-seed drivers in [`main.py`](../main.py) and
[`scripts/`](../scripts).

---

## 1. Trainer lifecycle

[`training/trainer.py::AgentGuardTrainer`](../training/trainer.py)

```
__init__(model, train_loader, val_loader, config, ...)
   │
   ├── Build HybridLoss (4 terms, λ weights from config)
   ├── Build optimizer (adam / adamw)
   ├── Build scheduler (cosine / plateau / onecycle)
   │     • onecycle → step-per-batch (step_per_batch=True)
   │     • cosine/plateau → step-per-epoch
   └── Configure checkpoint path, max_grad_norm, early-stop patience

fit()
   │
   for epoch in 1..epochs:
   │   train_epoch()    # non-finite total losses → skip; grad clip; step_per_batch
   │   validate()       # metrics at threshold 0.5: AUROC / AUPRC / F1 / P / R
   │   scheduler.step() # unless step_per_batch already stepped
   │   log epoch (stdout + .log file + _epochs.csv)
   │   optuna pruning check (if trial is attached)
   │   if AUROC improved:
   │       save checkpoint (epoch, model/optim state, val_loss, metrics)
   │   else:
   │       epochs_without_improvement += 1
   │       break if patience exceeded
   │
   return best_metrics

evaluate(test_loader)
   │
   load best checkpoint → forward over test_loader → return (losses, metrics)
```

## 2. Selection criterion

The trainer selects on **AUROC** rather than F1 or val_loss:

- F1 at threshold 0.5 is misleading under class imbalance — an epoch-1
  model that predicts all-anomalous has `recall=1.0`, `precision ≈ base_rate`,
  and a deceptively high F1 on some folds.
- AUROC is threshold-independent and reflects ordering quality, which is
  what downstream thresholding (see §4) actually needs.

Comment preserved in the code (`trainer.py` around the `current_auroc`
check) records this decision and why.

## 3. Loss terms

| Term | Source | Default λ | Best-config λ |
|---|---|---|---|
| `recon` | `ReconstructionLoss` — MSE(Stream 1) + masked MSE(Stream 2) | 1.0 | 1.84 |
| `contrastive` | `SupervisedContrastiveLoss` — SupCon w/ class upweight | 1.0 | 1.50 |
| `temporal` | `TemporalSmoothnessLoss` — L2 between latents of adjacent same-agent windows | 0.1 | 0.013 |
| `cls` | Weighted BCE on `anomaly_head(sigmoid)` with NaN guard | 1.0 | 1.0 |

All four loss terms log their per-epoch averages to the `.log` file and the
per-epoch CSV so you can diagnose which one dominates / stalls.

### 3.1 `TemporalSmoothnessLoss` — "same agent, adjacent window" detail

```python
same_agent = (agent_indices[1:] == agent_indices[:-1])
diffs = window_indices[1:] - window_indices[:-1]
adjacent_mask = same_agent & (diffs == 1)
loss = latent_dists[adjacent_mask].mean()
```

The mask is critical: without it, a batch contains samples from different
agents (because the DataLoader shuffles), and treating them as "adjacent"
would penalise healthy cross-agent variance. In practice a minibatch usually
contains 2-5 truly adjacent pairs; batches with zero get a zero loss.

### 3.2 `_classification_loss` — NaN guard

```python
bad = ~torch.isfinite(scores)
if bad.any():
    scores = torch.where(bad, torch.full_like(scores, 0.5), scores)
scores = scores.clamp(1e-7, 1.0 - 1e-7)
weights = torch.where(labels > 0.5, class_weight_ratio, 1.0)
return F.binary_cross_entropy(scores, labels.float(), weight=weights)
```

Why the guard exists: on Hopper/Ada with TF32 enabled, the Mamba SSM
prefix-scan occasionally produced `Inf` → `sigmoid(Inf) = NaN` →
`BCELoss(NaN, ...)` → device-side assertion → whole process dies. Replacing
the NaN with 0.5 costs one false prediction; `set_global_seed` now disables
TF32 by default so this path is cold, but kept as belt-and-braces.

---

## 4. Thresholding

The trainer reports F1 at `threshold = 0.5`. For serving / evaluation, use
the validation-set-tuned threshold from
[`baselines/run_baselines.py::pick_threshold`](../baselines/run_baselines.py):

```python
def pick_threshold(scores_val, labels_val):
    thrs = np.quantile(scores_val, np.linspace(0, 1, 101))
    best_f1, best_t = -1.0, 0.5
    for t in thrs:
        f1 = f1_score(labels_val, (scores_val >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t
```

`scripts/run_fold.py` uses this helper to pick a fold-specific threshold on
the val set before computing final test metrics.

---

## 5. Cross-validation

### 5.1 Stratified folds

`main.make_stratified_folds(attacked, control, k)` is **tier-aware**:

```
tier1 = attacked_agents[:5]   # ~100 anomalies each
tier2 = attacked_agents[5:8]  # ~21 anomalies each
tier3 = attacked_agents[8:]   # ~13 anomalies each
controls = control_agents

for tier in [tier1, tier2, tier3, controls]:
    for i, agent in enumerate(tier):
        folds[i % k].append(agent)
```

With `k=5`: every fold gets 1 Tier 1 + 0-1 Tier 2 + 1-2 Tier 3 + 1 control
agent. This keeps the positive-rate proportional across folds.

### 5.2 Fold roles per iteration

For each fold `i`:

- **test** = `folds[i]`
- **val** = `folds[(i+1) % k]`
- **train** = everything else

val and test never overlap, so the early-stop criterion (val) doesn't leak
into test metrics.

### 5.3 Running CV

```bash
python main.py --mode cv --config config_best.yml
```

Per fold:
- Fresh model (no warm start across folds).
- Checkpoint → `data/processed/checkpoints/best_model_fold{i}.pt`.
- Per-fold `.log` and `_epochs.csv` under `logs/`.
- Summary AUROC mean ± std printed at the end.

Aggregate CV detail is in [`results/results.md`](../results/results.md).

---

## 6. Multi-seed (scripts/train_multiseed.py)

```bash
python scripts/train_multiseed.py \
    --config config_best.yml \
    --seeds 42,1337,2024 \
    --out_dir .
```

Trains `N_seeds × K_folds` independent runs. Per run outputs:

- `logs/seed{S}_fold{F}_epochs.csv`
- `data/processed/checkpoints/model_seed{S}_fold{F}.pt`
- `predictions/agentguard_seed{S}_fold{F}.npz`
  — `y_true`, `y_score`, `attack_id`, `attack_category`, `agent_id`, `window_idx`
- `latents/agentguard_seed{S}_fold{F}.npz`
  — same metadata plus `latent` `[N, latent_dim]`

Used as input to the plot stage (latent-space embeddings, ROC/PR across
seeds) and the interpretability stage (per-sample attribution from the
test-fold checkpoint).

---

## 7. Parallel execution

`scripts/run_full_pipeline.sh` uses GNU `parallel` to fan out multi-seed
training across GPUs:

```bash
parallel -j "$N_GPUS" --colsep ' ' --line-buffer \
    --joblog logs/stage1_joblog.tsv \
    'CUDA_VISIBLE_DEVICES=$(({%}-1)) python scripts/train_multiseed.py \
        --config config_best.yml --seeds {1} --folds {2} --out_dir . \
        > logs/stage1_s{1}_f{2}.log 2>&1' \
    ::: 42 1337 2024 ::: 1 2 3 4 5
```

15 jobs, one per (seed, fold), pinned to GPU `{slot-1}`. Failed jobs can be
re-run with `parallel --retry-failed --joblog logs/stage1_joblog.tsv`.

Parallelism cap is 7 (one H200 cluster node) — tune with `--gpus N` or the
`N_GPUS` environment variable.

---

## 8. Logging

[`utils/logging.py`](../utils/logging.py) exposes:

- `setup_run_logger(mode, config, log_dir, trial_number=None, phase=None)` →
  opens `.log` with timestamp + run type + trial ID.
- `log_config(logger, config)` → writes the flattened config under `[CONFIG]`.
- `log_epoch(...)` / `log_results(...)` / `log_test_results(...)` — canonical
  formatters.
- `EpochCSVWriter` — context manager; writes a machine-readable per-epoch
  CSV beside the `.log` file (columns: epoch, all four train/val losses,
  metrics, lr).

Every sweep trial also writes its own trial log with `trial_number` and the
Phase number so the sweep directory stays legible.

---

## 9. Reproducibility checklist

Before claiming results are reproducible:

1. `set_global_seed(42)` is called at the top of `main()`.
2. TF32 matmul / cudnn explicitly disabled.
3. Same preprocessed `.pt` files used (hash or timestamp-check `data/processed/`).
4. Same `config.yml` or `config_best.yml` — the `.log` header records the
   flattened config.
5. Same PyTorch major version (pin to the one in `requirements.txt`).
6. Same CUDA major version (matters for cuBLAS reductions).

Exact bit-for-bit reproducibility across GPUs of different generations is
**not** guaranteed — cuBLAS and cuDNN algorithm selection differs. Mean
metrics across seeds are stable to within ~0.01 AUROC.

---

## 10. Common patterns

### 10.1 Warm-start a longer run from a sweep winner

Apply best params then continue training with a higher epoch budget:

```bash
python -m utils.apply_best_params           # writes config_best.yml
python main.py --mode train --config config_best.yml
```

Increase `training.epochs` and `training.early_stopping_patience` in
`config_best.yml` if the sweep stopped trials early.

### 10.2 Evaluate a checkpoint from a different run

```yaml
# test_config.yml
inference:
  checkpoint_path: "data/processed/checkpoints/best_model_fold3.pt"
data:
  test_agents: [agent-4, agent-12, agent-19]
```

```bash
python main.py --mode test \
    --config test_config.yml \
    --weights_config config_best.yml      # architecture of the checkpoint
```

Writes `results.md` with per-agent confusion matrices and overall metrics.

### 10.3 Drive training from a notebook

Use `scripts/run_fold.py` as a subprocess per fold:

```bash
python scripts/run_fold.py \
    --config-json /tmp/cfg.json \
    --train-agents agent-1,agent-2,... \
    --val-agents   agent-3,... \
    --test-agents  agent-4,... \
    --out-json     /tmp/metrics_fold1.json \
    --checkpoint-suffix notebook_job0
```

One subprocess per fold means each run gets its own CUDA context; use
`CUDA_VISIBLE_DEVICES=X` to pin each to a specific GPU.
