# Troubleshooting

Symptoms you're likely to hit, with root cause and fix. If you find a
new failure mode, add it here.

---

## Environment

### `torch.cuda.is_available() == False` after `pip install torch`

**Cause:** PyPI's default `torch` wheel is CPU-only.

**Fix:**

```bash
pip install --index-url https://download.pytorch.org/whl/cu124 torch
```

`scripts/run_full_pipeline.sh` does this automatically on a fresh host.

### `ImportError: No module named 'paramiko'`

**Cause:** Paramiko is listed in `requirements.txt` but `run_full_pipeline.sh`
filters it out to avoid pulling distutils-installed transitive deps on
minimal containers.

**Fix:** `pip install paramiko>=3.4.0` manually on hosts that need the
dashboard.

### `sqlite3: unable to open database file` in sweep

**Cause:** `sweep/results/` doesn't exist.

**Fix:** `mkdir -p sweep/results` — the sweep auto-creates it normally,
but custom CWD can confuse the relative path.

---

## Training

### Fold collapses — `auroc ≈ base_rate`, `recall=1.0`

**Symptom:** Folds 1 and 3 show 0.04 AUROC / 0.09 F1 with perfect recall.

**Root cause:** Under heavy class imbalance, the weighted BCE dominates
the contrastive signal when certain test agents are dominated by Tier 3
(low-anomaly) agents. The trainer picks an epoch-1 all-anomalous
predictor as "best" because AUROC hasn't degraded from it yet.

**Fixes (in order of least → most invasive):**

1. Run multi-seed (`scripts/train_multiseed.py`) and aggregate across
   seeds. Different shuffle orders change which batches form positive
   pairs and can lift the fold out of collapse.
2. Ensemble top-K sweep configs (`python -m sweep.ensemble --top-k 3`).
   A bad-fold in one config is typically not a bad-fold in another.
3. Increase `training.class_weight_ratio` to 4-5 in `config_best.yml`
   and retrain the specific fold.
4. Lower `training.lambda_cls` (e.g. to 0.3) so the contrastive signal
   has more relative weight early on.

Expected after fixes: AUROC for Folds 1/3 rises from ~0.05 to ~0.4-0.6
(still lower than Folds 2/4/5 but no longer degenerate).

### BCELoss device-side assertion on Hopper (H100/H200)

**Symptom:**

```
RuntimeError: CUDA error: device-side assert triggered
Assertion `input_val >= zero && input_val <= one` failed.
```

**Root cause:** TF32 matmul on Hopper reduces mantissa precision just
enough that the Mamba SSM prefix-scan overflows to `Inf` →
`sigmoid(Inf) = NaN` → BCELoss assertion → process death.

**Fix (already applied in this repo):**

- `main.set_global_seed` disables TF32 via `allow_tf32 = False` and
  `torch.set_float32_matmul_precision("highest")`.
- `HybridLoss._classification_loss` replaces non-finite `anomaly_score`
  with `0.5` before BCE.

If you're writing a custom driver, call `set_global_seed(42)` first.

### `RuntimeError: CUDA out of memory` in sweep

**Root cause:** Some Phase 1 architecture combinations (e.g.
`d_model=512, latent_dim=256, transformer_ff_dim=1024`) do not fit on a
single mid-range GPU.

**Expected behaviour:** The sweep objective catches OOM, empties the
CUDA cache, and returns `0.0` for that trial so the pruner can avoid the
configuration in later trials.

**Mitigations:**

- Shrink the Phase 1 `d_model` search space to drop `512`.
- Export `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` for better
  memory fragmentation behaviour on H100+.

### Early stop at epoch 1 — training never recovers

**Symptom:** `Early stopping at epoch {patience}` before any meaningful
improvement.

**Diagnoses:**

- Val set too small (agent-level CV + small test fold). Increase
  `early_stopping_patience`.
- LR too high. With `onecycle + lr=2.5e-3`, the schedule's warmup
  depends on `epochs` — if you also dropped `epochs` to 10, the warmup
  phase never lets the model escape the all-anomalous local minimum.
  Use `cosine` instead, or keep `epochs >= 50`.

### Per-epoch CSV has only the header

**Cause:** Trainer crashed before the first epoch completed, or
`epoch_csv.close()` ran but no row was written.

**Fix:** Check the adjacent `.log` file for the crash traceback; common
reasons are a shape mismatch in `stream1` (seq_context in config doesn't
match preprocessed data), or a missing `.pt` file.

---

## Sweep

### Optuna study "phase1_architecture" not found

**Cause:** You pointed `sweep.analysis` at a database that doesn't have
a run of that study yet.

**Fix:** Run the corresponding phase first
(`python -m sweep.run_sweep --phase 1`) or pass a different DB via
`OPTUNA_STORAGE`.

### Phase 4 results all show `mean_auroc ≈ 0.04`

**Cause:** Phase 4 runs strict 5-fold CV with a single seed (42). Folds
1 and 3 collapse under the same conditions described in "Fold collapses"
above, pulling the mean down.

**Workaround:** Trust Phase 3's values (which use 3-fold) for selecting
the best configuration, or re-run Phase 4 with multi-seed support
(modify `run_phase4` in `sweep/run_sweep.py` to loop over seeds).

---

## Data pipeline

### Preprocessing skips every agent ("No data found")

**Cause:** `config.data.date` doesn't match the date component of the
JSONL filenames, or the per-agent directory is nested one level too
deep.

**Fix:**

```bash
# Verify the layout
ls data/dataset/agentguard-all-batches/agent-1/telemetry/
# Should show: 2026-03-15.jsonl

# If the date differs, update config.yml::data.date
```

### `attack_id` and `attack_category` are all empty strings in `.pt`

**Cause:** `batch/` manifest wasn't found at
`{raw_data_dir}/batch/*/attacks-*.jsonl`, or the manifest JSONL is
malformed.

**Fix:** Verify the manifest exists and is valid JSONL. The loader is
tolerant of malformed lines (skips them silently), so a single bad line
won't raise — but it won't contribute an `attack_id` either.

### `stream2_seq` is all zeros for many windows

**Cause:** Window has no action records. This is expected for benign
windows when the agent is idle between tasks.

**Fix:** Not a bug. `stream2_mask` will also be all zeros for those
windows, and the cross-attention path safely handles all-padded rows via
`_safe_key_padding_mask`.

---

## Dashboard

### Dashboard hangs on startup

**Cause:** SSH key path is wrong, or the remote host is unreachable.
Paramiko doesn't time out quickly by default.

**Fix:** In the sidebar, verify the private key path (usually
`~/.ssh/id_rsa`) and the host. Test SSH manually from the same machine:

```bash
ssh -i ~/.ssh/id_rsa user@host "echo ok"
```

### Dashboard score is stuck at 0.5

**Cause:** Model is producing NaN. The BCE guard replaces NaN with 0.5,
which the dashboard displays verbatim.

**Fix:** Confirm `dashboard.py` loads the right checkpoint and that
`torch.set_float32_matmul_precision("highest")` + TF32 disable is
applied when the dashboard initializes the model.

### Log files on the server don't append to dashboard

**Causes:**

- Poll interval longer than write rate — bump `POLL_INTERVAL_SEC` down.
- Wrong paths — `TELEMETRY_LOG_DIR` / `ACTIONS_LOG_DIR` at the top of
  `dashboard.py` must match the agent host's actual paths.
- Wrong date — JSONL filenames rotate at UTC midnight; the dashboard
  has to follow the filename change.

---

## Interpretability

### Report driver dumps "checkpoint missing" and uses random init

**Cause:** `data/processed/checkpoints/model_seed{seed}_fold{fold}.pt`
doesn't exist for the requested seed/fold.

**Fix:** Run `scripts/train_multiseed.py` first (or
`main.py --mode cv`) so the checkpoint is created. The driver warns
but continues with a random-init stub so the pipeline plumbing can be
validated end-to-end.

### Attention PNG is blank or all-black

**Cause:** Masked region is enormous (window with no action events) so
every attention weight is ≈0 or ≈1/T (uniform).

**Fix:** Pick a different sample. Benign windows with no events are not
interesting for attribution analysis.

### `plot_attention_heatmap` throws `ValueError: setting an array element with a sequence`

**Cause:** Attention tensor wasn't moved to CPU before numpy conversion,
or the batch dim wasn't squeezed.

**Fix:** Ensure `return_attention=True` is only requested with
`fusion_strategy="cross_attention"`; the non-cross-attention paths
return no attention tensor.

---

## CI / scripts

### `parallel: command not found`

**Cause:** GNU Parallel isn't installed.

**Fix:**

```bash
# Debian/Ubuntu
apt-get install -y parallel

# macOS
brew install parallel
```

### `run_full_pipeline.sh` exits with "Stage 1 did not produce all 15 artifacts"

**Cause:** One or more (seed, fold) jobs failed.

**Fix:** Inspect `logs/stage1_joblog.tsv` and individual `logs/stage1_s*_f*.log`
files. Re-run failures only:

```bash
parallel --retry-failed --joblog logs/stage1_joblog.tsv
```

### `umap-learn` missing after pipeline install

**Cause:** Some minimal images exclude `umap-learn` from the filtered
`requirements_pipeline.txt`.

**Fix:** The pipeline script does a belt-and-braces re-install:
`python -c "import umap" 2>/dev/null || pip install umap-learn`.

---

## When to file a bug

All of the above are known behaviours. Open an issue if you hit:

- A numerical NaN that survives the BCE guard.
- A shape mismatch in `build_loaders_from_splits` that isn't caused by
  `seq_context` drift between config and preprocessed data.
- A fusion strategy that works in smoke tests but crashes on real data.
- Non-determinism in CV metrics larger than ~0.05 AUROC across seeds.

Include: Python version, `torch.__version__`, GPU name, `config.yml`
diff against main, and the failing command with full stdout/stderr.
