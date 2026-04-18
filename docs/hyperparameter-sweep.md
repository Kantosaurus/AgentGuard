# Hyperparameter sweep

A four-phase Optuna workflow that searches architecture → training dynamics
→ loss/data, then runs a full 5-fold CV on the top-K from phase 3.
Implementation: [`sweep/`](../sweep/).

---

## 1. Design

Searching every axis at once wastes compute: architecture trials train
cheap single-split jobs, but training-dynamics and loss-weight searches
only make sense once the architecture is fixed. The sweep therefore
freezes earlier-phase winners when it enters each new phase.

### 1.1 Phase 1 — architecture

- **Trials:** 100 by default (`PHASE_DEFAULTS[1]["n_trials"] = 100`)
- **Folds:** 0 (single train/val split from `config.data.*_agents`)
- **Pruner:** `MedianPruner(n_startup=5, n_warmup_steps=10)` — drops
  trials whose AUROC trajectory is below median after epoch 10.
- **Search axes:**
  - `d_model ∈ {64, 128, 256, 512}`
  - `latent_dim ∈ {64, 128, 256}`
  - `mamba_layers ∈ {1, 2, 3, 4, 6}`
  - `transformer_layers ∈ {1, 2, 3, 4, 6}`
  - `transformer_heads ∈ {h ∈ {2,4,8} : d_model % h == 0}` (dependent)
  - `transformer_ff_dim ∈ {256, 512, 1024}`
  - `dropout ∈ {0.0, 0.05, 0.1, 0.2, 0.3}`
  - `fusion_strategy ∈ {cross_attention, concat_mlp, gated, attention_pool}`
  - `cls_head_layers ∈ {1, 2, 3}`, `cls_head_hidden_dim ∈ {32, 64, 128, 256}`
  - `cls_head_activation ∈ {relu, gelu, silu}`
  - `decoder_activation ∈ {relu, gelu, silu}`

Head-count divisibility is enforced to avoid `nn.MultiheadAttention`
errors.

### 1.2 Phase 2 — training dynamics

- **Trials:** 60
- **Folds:** 3 (stratified k=3 to cut wall-clock)
- **Locked:** Phase 1 best params.
- **Search axes:**
  - `lr ∈ [1e-4, 3e-3]` (log-uniform)
  - `optimizer ∈ {adam, adamw}`
  - `scheduler ∈ {cosine, plateau, onecycle}`
  - `batch_size ∈ {16, 32, 64, 128, 256, 512}`
  - `grad_clip ∈ {0.5, 1.0, 2.0, 5.0}`
  - `weight_decay ∈ [1e-5, 1e-2]` (log-uniform, adamw only)

### 1.3 Phase 3 — loss + data

- **Trials:** 60
- **Folds:** 3
- **Locked:** Phases 1 + 2 best params.
- **Search axes:**
  - `lambda_recon ∈ [0.1, 2.0]`
  - `lambda_contrastive ∈ [0.1, 2.0]`
  - `lambda_temporal ∈ [0.01, 0.5]` (log-uniform)
  - `seq_context ∈ {4, 8, 16}`
  - `augmentation ∈ {none, feature_mask, time_jitter, mixup}`
  - `class_weight_ratio ∈ [1.0, 5.0]`
  - `augmentation_prob ∈ [0.1, 0.5]` (only if augmentation ≠ none)

### 1.4 Phase 4 — final CV on top-K

- **Trials:** 0 new. Loads top-K from Phase 3 Optuna study, runs each
  through full 5-fold CV with fixed seed 42.
- Writes `phase4_results.json` plus `best_params_phase4.json` for the
  highest-mean-AUROC survivor.

---

## 2. Running a sweep

### 2.1 Sequential single-node

```bash
python -m sweep.run_sweep --phase 1 --n-trials 100
python -m sweep.run_sweep --phase 2 --n-trials 60
python -m sweep.run_sweep --phase 3 --n-trials 60
python -m sweep.run_sweep --phase 4
```

or just:

```bash
python -m sweep.run_sweep --phase all
```

### 2.2 Distributed (multiple workers against a shared DB)

Each worker needs its own `OPTUNA_STORAGE`:

```bash
# On all workers:
export OPTUNA_STORAGE="postgresql://optuna:***@dbhost/agentguard_sweep"

# Worker 1..N:
python -m sweep.run_sweep --phase 1 --n-trials 100
```

Optuna's `load_if_exists=True` means each worker joins the same study; the
`MedianPruner` state is shared across workers via the DB.

SQLite WAL mode for local multiprocess:

```bash
sqlite3 sweep/results/optuna.db "PRAGMA journal_mode=WAL;"
```

### 2.3 OOM handling

`sweep/objective.py::objective` catches `CUDA out of memory` and returns
`0.0` (the minimum AUROC), so a pathological config doesn't abort the
sweep. Pair with `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` on
Hopper if memory fragmentation becomes an issue.

---

## 3. Objective wrapping

```python
objective = create_objective(base_config, phase, best_params, n_folds)
study.optimize(objective, n_trials=n_trials)
```

Per trial:
1. Call the Phase-N `suggest_*` helper to generate overrides.
2. `override_config` deep-merges them onto `base_config`.
3. `_set_seed(42)` seeds everything (and disables TF32).
4. If `n_folds > 0`, run `make_stratified_folds` and call `_run_single_fold`
   per fold — the **first** fold is attached to the Optuna trial so
   pruning can kick in after ~10 epochs.
5. Return the mean val F1 across folds (or the single-split F1 if
   `n_folds == 0`).

The metric is currently **F1** despite the study being named in
AUROC-friendly terms — this is a known inconsistency, tracked in
`sweep/objective.py` comments. F1 was chosen because most folds are
AUROC-saturated but F1 separates recoverable vs degenerate configs.

---

## 4. Post-sweep tooling

### 4.1 Inspect a phase

```bash
python -m sweep.analysis --phase 1
python -m sweep.analysis --phase all
```

Outputs per phase:

- Total / completed / pruned trial counts.
- Best trial id, AUROC, full params.
- `optuna.importance.get_param_importances` (Pearson) with an ASCII bar
  chart of each parameter's importance.
- Top-10 configs sorted by value, with key params inlined.

### 4.2 Apply best params to `config_best.yml`

```bash
python -m utils.apply_best_params
```

Reads the four `best_params_phase{1..4}.json` files, deep-merges them onto
`config.yml`, writes `config_best.yml`. The downstream scripts
(`train_multiseed.py`, `run_full_pipeline.sh`) consume this file.

### 4.3 Ensemble of top-K

```bash
python -m sweep.ensemble --top-k 3 --config config.yml
```

Trains each of the top-K Phase-3 configs from scratch on the full train
set (minus the last 3 agents for val), evaluates each on the test set,
then combines via three strategies:

- **Simple averaging** — equal-weight mean of raw sigmoid scores.
- **Weighted averaging** — weights ∝ each model's val AUROC.
- **Majority vote** — thresholded votes averaged.

Threshold per strategy is picked for best F1 on the fly via sklearn's PR
curve; writes `sweep/results/ensemble_results.json`.

---

## 5. Results under version control

Each phase writes:

- `sweep/results/best_params_phase{N}.json`
- `sweep/results/trials_phase{N}.csv` (full DataFrame from `study.trials_dataframe()`)
- `sweep/results/optuna.db` (SQLite WAL)
- `sweep/results/phase4_results.json` (only for phase 4)

Commit everything except `optuna.db` if the repository is private; the DB
reproduces from the CSV when needed but grows quickly and bloats diffs.

---

## 6. Historical best params (current `config_best.yml` derivation)

From the JSONs in `sweep/results/` at time of writing:

**Phase 1 — architecture**
```json
{
  "d_model": 128,
  "latent_dim": 256,
  "mamba_layers": 4,
  "transformer_layers": 1,
  "transformer_heads": 8,
  "transformer_ff_dim": 1024,
  "dropout": 0.3,
  "fusion_strategy": "cross_attention",
  "cls_head_layers": 1,
  "cls_head_hidden_dim": 32,
  "cls_head_activation": "gelu",
  "decoder_activation": "gelu"
}
```

**Phase 2 — training**
```json
{
  "lr": 0.00250748,
  "optimizer": "adam",
  "scheduler": "onecycle",
  "batch_size": 16,
  "grad_clip": 1.0
}
```

**Phase 3 best params (non-CV):**
```json
{
  "lambda_recon": 1.797,
  "lambda_contrastive": 1.464,
  "lambda_temporal": 0.0132,
  "seq_context": 8,
  "augmentation": "none",
  "class_weight_ratio": 3.232
}
```

**Phase 4 winner (full 5-fold CV):**
```json
{
  "lambda_recon": 1.840,
  "lambda_contrastive": 1.503,
  "lambda_temporal": 0.01259,
  "seq_context": 8,
  "augmentation": "none",
  "class_weight_ratio": 2.457
}
```

Notable takeaways:

- **Cross-attention dominates** — no other fusion strategy reached the
  top-10 in Phase 1.
- **One transformer layer is enough** — depth hurt, reflecting the short
  (≤64) Stream 2 sequences.
- **High dropout (0.3) helps** — the 15-agent train set overfits quickly.
- **Small batch (16) with onecycle** beats larger batches. OneCycle's
  warmup window matters more than batch-level gradient averaging here.
- **Augmentation = none** — synthetic augmentation worsened rather than
  helped; the real-agent variance is enough.

---

## 7. Sweep design limitations

- **F1 vs AUROC mismatch.** Final model selection uses AUROC; the sweep
  optimises F1 per fold. Configs that are AUROC-strong but threshold-
  sensitive can lose to configs that pick a lucky F1 threshold. Migrating
  the objective to `mean(AUROC)` is tracked as a TODO in
  `sweep/objective.py`.
- **Phase 4 is CV-strict.** The currently saved `phase4_results.json`
  shows a mean AUROC of ~0.04 across the top-5 configs — this is the
  same fold-collapse pattern seen in [§9 of the README](../README.md#9-results)
  and is evidence that the CV fold selection matters as much as the
  hyperparameters. Multi-seed runs alleviate this.
- **No architecture search over state-space dim.** `mamba_state_dim` is
  coupled to `d_model` via `mamba_state_dim = d_model`; making them
  independent would double the search space but might unlock capacity
  wins.
- **No search over `max_seq_len`.** Stays fixed at 64 because preprocessing
  emits fixed-shape tensors; varying it would require re-preprocessing.

---

## 8. Quick reference

| Task | Command |
|---|---|
| Run one phase | `python -m sweep.run_sweep --phase N` |
| Run all phases | `python -m sweep.run_sweep --phase all` |
| Analyze | `python -m sweep.analysis --phase N` |
| Apply best | `python -m utils.apply_best_params` |
| Ensemble | `python -m sweep.ensemble --top-k 3` |
| Custom trial budget | `python -m sweep.run_sweep --phase 1 --n-trials 50` |
| Distributed DB | `OPTUNA_STORAGE=postgresql://... python -m sweep.run_sweep ...` |
