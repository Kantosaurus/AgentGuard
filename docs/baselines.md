# Baselines

Five anomaly-detection baselines, run under the same stratified 5-fold CV
as the main AgentGuard model, across 3 seeds (42, 1337, 2024). Code:
[`baselines/`](../baselines/). Results:
[`results/baselines.md`](../results/baselines.md).

---

## 1. Why these baselines

The baselines are selected to **bracket** the dual-stream hypothesis:

- **Isolation Forest** — unsupervised, tabular, no sequence. Our floor.
- **LSTM-AE, CNN-AE, Transformer-AE** — sequence-aware reconstruction
  models, each representing a different architecture family. They see
  Stream 1 as a sequence but have no Stream 2 access.
- **Deep SVDD** — non-reconstruction one-class learner. Stronger than
  AEs on normal-only training data because the embedding is explicitly
  penalised for drifting from the data center.

If AgentGuard's dual-stream fusion is real, it should outperform each of
these by a margin larger than the inter-baseline spread.

---

## 2. Input format

`baselines/features.py::build_fold_tensors` assembles per-(agent, window)
tensors from the preprocessed `.pt` files:

- **flat** — `[N, 32]` per-window Stream 1 feature vector.
- **seq** — `[N, seq_context, 32]` left-padded sliding window, same
  `seq_context` as AgentGuard (8 by default).
- **labels** — `[N]` (0/1).

Baselines **only see Stream 1**. Stream 2 is deliberately withheld to
isolate the contribution of multi-modal fusion.

---

## 3. Models

### 3.1 Isolation Forest

- Library: `sklearn.ensemble.IsolationForest`.
- `n_estimators=200`, `contamination = max(1e-4, min(train_anomaly_rate, 0.5))`.
- Scores are `−decision_function(x)` (higher = more anomalous).
- Trained on `train["flat"]` (includes anomalies — this is the one
  baseline that's supervised in a very loose sense, via contamination).

### 3.2 LSTM-AE

- Single-layer LSTM encoder → single-layer LSTM decoder, both hidden=64.
- Trained on **normal-only** samples (`labels == 0`).
- Loss: MSE between reconstruction and input.
- Anomaly score at test time = per-sample MSE over all feature dims.

### 3.3 CNN-AE

- 1-D Conv (kernel 3, padding 1) along the time axis.
- `Conv → ReLU → Conv → ReLU` encoder; symmetric decoder to input_dim.
- Normal-only training, MSE loss, MSE anomaly score.

### 3.4 Transformer-AE

- Project 32 → d_model=64, **LayerNorm**, then two stacks of
  `TransformerEncoderLayer` (2 layers each) as "encoder" and "decoder".
- The LayerNorm after projection matters: without it, raw telemetry
  features of varied scale saturate `softmax(Q·Kᵀ)` and produce NaN on
  some folds. This was discovered during an early baseline run and is
  preserved in `transformer_ae.py`.
- Normal-only, MSE, MSE score.

### 3.5 Deep SVDD (Ruff et al., 2018)

- 3-layer MLP, **no biases** anywhere in the network (required by the
  original paper to avoid a trivial all-zeros solution).
- Center `c` initialised as the mean of training embeddings; any
  component with `|c_i| < eps` is nudged to ±eps to avoid further
  collapse.
- Loss: `mean(sum_i (z_i - c_i)^2)` — squared distance to center.
- Anomaly score = same distance.

---

## 4. Train / score loops

Both defined in [`baselines/train_torch.py`](../baselines/train_torch.py):

- `train_ae(model, train_loader, val_loader, device, epochs, lr, weight_decay, patience, verbose)`
  — generic reconstruction training with early stopping on val MSE.
- `score_ae(model, loader, device)` — returns per-sample MSE and labels as
  numpy arrays; non-finite scores are replaced with 10× the max finite score
  so the anomalous-looking outliers stay ranked highest and sklearn's
  AUROC/AUPRC computation doesn't abort.

Deep SVDD has its own `train_deep_svdd` / `score_deep_svdd` in
[`baselines/models/deep_svdd.py`](../baselines/models/deep_svdd.py).

---

## 5. Threshold selection

Every baseline picks a **validation-set F1-optimal threshold** via
`baselines.run_baselines.pick_threshold`:

```python
thrs = np.quantile(scores_val, np.linspace(0, 1, 101))
# Choose threshold that maximizes F1 over validation
```

Then reports AUROC/AUPRC (threshold-independent) and F1 at that threshold
on the test fold. This ensures F1 comparisons between baselines are fair
and not confounded by any single baseline's scale bias.

---

## 6. Running the baselines

```bash
# Full run (50 epochs each, 3 seeds × 5 folds × 5 baselines = 75 jobs)
python baselines/run_baselines.py --config config_best.yml --seeds 42,1337,2024

# Smoke run (3 epochs each) — useful to validate the pipeline
python baselines/run_baselines.py --config config_best.yml --fast

# Single-seed
python baselines/run_baselines.py --config config_best.yml --seeds 42
```

### 6.1 Outputs

- `results/baselines.csv` — flat table: `baseline, seed, fold, auroc, auprc, f1, threshold`.
- `results/baselines.md` — same table, plus a mean±std summary per baseline.
- `predictions/{slug}_seed{S}_fold{F}.npz` — raw `y_true` + `y_score` per
  (baseline, seed, fold). Used by `scripts/plots/run_all.py` to draw the
  combined ROC / PR comparison.

### 6.2 Empty-split guard

When a fold's normal-only train or val split is empty (can happen if
stratified folds put all anomalous windows of a small tier into one
fold), the runner logs a skip message, writes a zeros row to the CSV, and
saves empty prediction arrays so the downstream plot loader can detect
and ignore that (baseline, seed, fold) cell.

---

## 7. Interpreting the headline numbers

From `results/baselines.md`:

| Baseline | AUROC | AUPRC | F1 |
|---|---|---|---|
| IsolationForest | 0.3870 ± 0.0301 | 0.0599 ± 0.0024 | 0.1131 ± 0.0043 |
| LSTMAE | 0.4502 ± 0.0780 | 0.0707 ± 0.0104 | 0.1489 ± 0.0044 |
| CNNAE | 0.3654 ± 0.0164 | 0.0675 ± 0.0156 | 0.1452 ± 0.0047 |
| TransformerAE | 0.4872 ± 0.0728 | 0.0713 ± 0.0078 | 0.1499 ± 0.0044 |
| **DeepSVDD** | **0.7732 ± 0.0045** | **0.1057 ± 0.0065** | **0.1911 ± 0.0106** |

**Order on AUROC:** DeepSVDD ≫ Transformer-AE ≈ LSTMAE > Isolation Forest ≈ CNNAE.

**DeepSVDD's dominance** is notable and matches the paper's claim that a
purpose-built one-class objective beats reconstruction on normal-only
training. DeepSVDD's AUROC variance across folds is an order of magnitude
lower than the AEs', suggesting its embedding-to-center formulation is
much more stable under fold composition changes.

**Reconstruction-based AE AUROCs ~0.4-0.5** tell us that raw reconstruction
error on 32-d Stream 1 telemetry is barely above random on this task —
precisely because most attacks don't leave a distinctive OS-level
fingerprint, and what they do leave looks enough like normal workload
variance to be missed.

---

## 8. Reading the gap to AgentGuard

AgentGuard's CV is bimodal (Folds 2/4/5 near-ceiling, Folds 1/3
degenerate). Comparing against baselines requires matched-fold
comparison:

- On **Folds 2/4/5**, AgentGuard achieves AUROC 0.977-0.996 / F1 0.62-0.92
  — beyond even DeepSVDD's best per-fold AUROC.
- On **Folds 1/3**, both AgentGuard and most baselines struggle — but
  DeepSVDD holds up (mean 0.77) whereas AgentGuard's AUROC collapses
  to ~0.03-0.05.

Takeaways for future work:

- **AgentGuard's ceiling is higher** (dual-stream fusion matters) but its
  floor is lower (sensitive to fold composition). Multi-seed and
  ensembling mitigate the floor issue.
- **DeepSVDD is a fairer benchmark** than reconstruction AEs because it's
  purpose-built for the task; its performance argues that the Stream 1
  feature vector does carry detection signal, just not *enough* on the
  strict CV folds.
- **The real win of AgentGuard** is in per-attack category F1 —
  `evaluation.md` shows it has qualitatively different error modes than
  DeepSVDD (fewer FN on Prompt Injection / Tool Chaining, which are
  Stream-2 dominant).

---

## 9. Extending with new baselines

1. Add a module under `baselines/models/your_model.py` with a class that
   subclasses `nn.Module` and implements `forward(x) → reconstruction`.
   For SVDD-style single-number embedding models, follow the pattern in
   `deep_svdd.py`.
2. Import and use in `baselines/run_baselines.py`'s per-fold loop,
   mirroring the LSTM-AE block (train → score val/test → compute metrics
   → save predictions NPZ).
3. Add your baseline name to `BASELINE_SLUGS` so the NPZ dump gets a
   consistent filename, and to `baselines_order` in the markdown writer.
4. Append to `results/baselines.md` automatically by re-running the
   driver — the markdown is regenerated from scratch each run.
