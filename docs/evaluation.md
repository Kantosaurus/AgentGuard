# Evaluation & Interpretability

Metrics, threshold selection, attention visualisation, per-sample
interpretability reports, and error analysis.

---

## 1. Metrics

Always reported together — each captures a different failure mode:

| Metric | Range | What it captures |
|---|---|---|
| **AUROC** | 0-1 | Ranking quality; threshold-independent |
| **AUPRC** | 0-1 | Precision-recall area; better than AUROC under heavy imbalance |
| **F1** | 0-1 | Harmonic mean of precision & recall at a fixed threshold |
| **Precision** | 0-1 | Fraction of positive predictions that are true positives |
| **Recall** | 0-1 | Fraction of true anomalies correctly flagged |

Computed in [`training/trainer.py::_compute_metrics`](../training/trainer.py)
via `sklearn.metrics`. Degenerate splits (only one class present) return
zeros for all metrics.

### 1.1 Why AUPRC matters here

The anomaly class is roughly 5% of all windows. AUROC remains attractive
even when the model is marginal, because a huge population of true
negatives easily produces a high negative-rate; AUPRC collapses under the
same conditions. Reading both together reveals the true detector quality.

---

## 2. Threshold selection

The trainer picks `threshold = 0.5` for F1 logging during training, but
this is *not* the threshold you want for deployment. Production use:

```python
# From baselines/run_baselines.py
def pick_threshold(scores_val, labels_val):
    thrs = np.quantile(scores_val, np.linspace(0, 1, 101))
    best_f1, best_t = -1.0, 0.5
    for t in thrs:
        preds = (scores_val >= t).astype(int)
        f1 = f1_score(labels_val, preds, zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t
```

This is the same helper used in [`scripts/run_fold.py`](../scripts/run_fold.py)
and by every baseline. Report test metrics using the val-tuned threshold;
never tune on test.

---

## 3. Per-fold CV detail

Cross-validation produces a matrix of per-fold metrics
(see [`results/results.md`](../results/results.md) and
`results_fold{1..5}.md`). The per-fold CSVs in `logs/` capture the full
training trajectory:

```
epoch,train_total,train_recon,...,val_total,...,auroc,auprc,f1,precision,recall,lr
1,      5.2341,    1.0345, ...,    4.9201,...,0.4612,0.0823,0.088, 0.047,  1.000, 0.000150
2,      4.9012,    0.9856, ...,    4.6122,...,0.7891,0.2341,0.321, 0.312,  0.334, 0.000750
...
```

Useful for:

- **Diagnosing fold collapse** — a fold that starts at `auroc=0.5` and
  stays there regardless of loss movement indicates an ordering problem
  (BCE dominating contrastive at that fold's class rate).
- **Comparing seeds** — multi-seed runs can be stitched by epoch and a
  mean ± stddev curve plotted.
- **Sanity-checking early stopping** — if best-epoch fell right at
  `early_stopping_patience`, the schedule may be too short.

---

## 4. Per-agent evaluation (`--mode test`)

`main.do_test()` produces a Markdown report with per-agent confusion
matrices and overall metrics. Call via:

```bash
python main.py --mode test \
    --config test_config.yml \
    --weights_config config_best.yml
```

Sample output in [`results/test_results.md`](../results/test_results.md).
Useful for:

- Spotting agents that the model is systematically bad at (e.g. very low
  attack volume → zero-FP bar is brittle).
- Validating that control agents have zero TP (any TP is a false
  positive, and they should always be wrong).

---

## 5. Latent-space visualisation

`scripts/plots/run_all.py` draws:

- **`results/figures/latent_tsne.pdf`** — 2-D t-SNE of test-fold latents,
  coloured by `y_true` (0/1) and styled by `attack_category`. A
  separation-of-clusters picture is the fastest way to tell whether the
  fused latent is actually using class information.
- **`results/figures/latent_umap.pdf`** — same but with UMAP. Different
  global-geometry tradeoffs; side-by-side is more informative than
  either alone.

Underlying data: `latents/agentguard_seed{S}_fold{F}.npz` from
`train_multiseed.py` contains `latent`, `y_true`, `attack_id`,
`attack_category`, `agent_id`, `window_idx`.

---

## 6. Attention visualisation

The cross-attention fusion module caches its per-head weights on
`self._last_attn_weights` after every forward pass (see
[`models/fusion.py`](../models/fusion.py)). Two avenues:

### 6.1 Aggregated: `attention_by_category.pdf`

`scripts/plots/run_all.py` loads the test-fold predictions + attention
captures, groups by `attack_category`, and draws mean heatmaps:

- `1to2` direction: `[T1=8, T2=64]` — which Stream 2 positions does each
  Stream 1 context window attend to, per category.
- `2to1` direction: `[T2=64, T1=8]` — converse.

Per-category means expose attack-specific attention patterns — e.g.,
exfiltration attacks concentrate attention on action positions containing
`tool_call(read_file) → tool_call(web_request)` sequences.

### 6.2 Per-sample: interpretability reports

`scripts/generate_interpretability_reports.py` generates a Markdown +
PNG pair per selected sample; see §7.

---

## 7. Interpretability reports

Generated by `scripts/generate_interpretability_reports.py`, using the
`agentguard.interpretability` package (Integrated Gradients attribution,
action-pair flagging, feature-wise z-scores vs per-agent benign baseline).

### 7.1 Sample selection

For each attack category present in the test fold:
- Top-N (`--n_per_category`) **true positives** ranked by model score.

Plus globally:
- Top-N **false positives** (`y_true=0, y_score ≥ 0.5`) by highest score.
- Top-N **false negatives** (`y_true=1, y_score < 0.5`) by lowest score.

### 7.2 Report structure

Each generated report contains:

1. **Header** — attack id, ground truth, model score.
2. **Temporal attribution heatmap** — Integrated Gradients on
   `stream2_seq` + `stream1` contributions over time. PNG saved next to
   the Markdown.
3. **Top flagged action pairs** — which (prev_event, curr_event)
   transitions in Stream 2 most increased the anomaly score. Shows tool
   names and event types.
4. **Top feature deviations** — the Stream 1 features with the highest
   absolute z-score against the agent's benign baseline. Helps confirm
   "this agent is doing something unusual" for FP cases where action
   sequence alone looks normal.

Output layout:

```
results/reports/
├── index.md                          # Auto-generated TOC
├── Prompt Injection/                 # Per-category folders
│   ├── agent-2_123.md
│   └── agent-2_123_attr.png
├── Tool Chaining/
│   └── ...
├── false_positives/
│   └── agent-16_445.md
└── false_negatives/
    └── agent-14_35.md
```

### 7.3 Running

```bash
python scripts/generate_interpretability_reports.py \
    --config config_best.yml \
    --seed 42 \
    --fold 1 \
    --out_dir results/reports \
    --n_per_category 3 \
    --ig_steps 50
```

Requires a trained checkpoint at
`data/processed/checkpoints/model_seed{seed}_fold{fold}.pt`; falls back
to a random-init stub if missing (and prints a clear warning) so the
driver can smoke-test end-to-end.

---

## 8. Error analysis patterns

### 8.1 Fold collapse (Folds 1/3)

Symptoms:

- `recall=1.0, precision ≈ base_rate`, `auroc ≈ base_rate`.
- Val metric plateaus from epoch 1.
- Best checkpoint is epoch 1 because later epochs don't improve AUROC
  (they just rearrange the ordering slightly under heavy BCE gradients).

Root cause: the test fold's positive-rate is too low / agents too small,
so the contrastive loss has too few positive pairs per batch, and the
weighted BCE dominates into an "always positive" solution.

Mitigations:

- **Multi-seed**: a different seed can pair batches differently and lift
  the fold out of the local minimum.
- **Ensemble**: `sweep.ensemble` weighted-average across top-K configs
  usually pulls a degenerate fold out of collapse.
- **Higher `class_weight_ratio`**: Phase 3 searched this and chose
  ~2.46, but some folds need ~4-5.
- **Warmup contrastive**: ramp `lambda_contrastive` from 0 → target over
  the first 10 epochs so BCE doesn't dominate. Not yet implemented;
  tracked as future work.

### 8.2 False positives on control agents

Rare in the headline runs (control agents produced 1-2 FPs total across
the test set), but when they occur they almost always correlate with:

- An unusual tool call pattern that doesn't appear in training (new tool
  hash bucket).
- A long, genuinely busy window on the dispatcher-driven agent — the
  control group deliberately gets real workload, so spikes happen.

Manual review via the interpretability report typically tells these
apart from true positives by the **absence** of Stream 1 deviations and
the lack of anomalous source labels in the flagged action pairs.

### 8.3 False negatives on tail attack categories

Indirect Injection (II) is a single-variant category with few training
samples; it predictably has the highest FN rate. Data augmentation was
explored (Phase 3 of the sweep) but did not help — the variance within
the II prompts is too high for masking / jitter to fill the gap.

Targeted fixes tracked for future work:

- Over-sampling II in `AgentGuardDataset` with weighted sampling.
- Category-conditional contrastive loss (push II samples toward each
  other as well as away from normals).

---

## 9. Writing new metrics

`trainer._compute_metrics` is static and self-contained; add a metric by:

1. Import the sklearn function at the top of `trainer.py`.
2. Compute it inside the method, handling the single-class edge case.
3. Include it in the returned dict.
4. Update `trainer._log` / `log_epoch` formatters in `utils/logging.py`
   and the `EpochCSVWriter.COLUMNS` list.

All three places must agree, otherwise the `.log` and CSV drift apart.
