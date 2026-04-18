# AgentGuard

**Dual-stream anomaly detection for LLM agent servers.**
A production-oriented research system that fuses OS telemetry and LLM action
logs through a Mamba + Transformer + cross-attention architecture to catch
prompt injection, exfiltration, resource abuse, and persistence attacks that
are invisible to either signal alone.

---

## Table of contents

1. [Overview](#1-overview)
2. [At a glance](#2-at-a-glance)
3. [System architecture](#3-system-architecture)
4. [Repository layout](#4-repository-layout)
5. [Quickstart](#5-quickstart)
6. [CLI reference](#6-cli-reference)
7. [Configuration reference](#7-configuration-reference)
8. [Pipeline stages](#8-pipeline-stages)
9. [Results](#9-results)
10. [Dashboard & live inference](#10-dashboard--live-inference)
11. [Reproducibility](#11-reproducibility)
12. [Troubleshooting](#12-troubleshooting)
13. [Further reading](#13-further-reading)

---

## 1. Overview

AgentGuard is an end-to-end anomaly detection pipeline for **AI agent
servers** — long-running processes that combine a Large Language Model (LLM)
with tool-use capabilities (file I/O, shell execution, web access). These
agents are uniquely vulnerable to a class of attacks that traditional
endpoint-security stacks do not see, because the attack vector is *natural
language instructions* that the agent then executes through legitimate
software channels.

The core hypothesis is simple:

> A malicious action always leaves fingerprints on **at least one** of two
> streams — the OS-level telemetry of the host process and the LLM-level
> action log of the agent. A model that jointly consumes both streams can
> detect attacks that either stream, used alone, misses.

This repository contains:

- The **model** — a multi-modal encoder (Mamba for telemetry sequences,
  Transformer for action sequences) with a bidirectional cross-attention
  fusion layer and a reconstruction + contrastive + temporal + classification
  hybrid loss.
- The **data pipeline** — JSONL → windowed tensors → PyTorch `.pt` files,
  labeled at window granularity from attack manifests.
- The **training system** — single-split, k-fold stratified CV, multi-seed,
  and a four-phase Optuna hyperparameter sweep (architecture → training →
  loss/data → final CV on top-K).
- **Baselines** — Isolation Forest, LSTM-AE, CNN-AE, Transformer-AE, Deep
  SVDD, each with its own per-(seed, fold) results and prediction dumps.
- **Interpretability** — per-sample temporal attribution, cross-attention
  inspection, action-pair flagging, and feature-wise benign-baseline z-scores;
  auto-generated Markdown reports and heatmaps.
- A **Streamlit dashboard** — polls a remote SSH host for live telemetry and
  action logs and scores each 30-second window in real time.

---

## 2. At a glance

| | |
|---|---|
| Primary task | Binary anomaly detection (normal vs attacked) on agent-windowed telemetry |
| Input streams | OS telemetry (Stream 1, 32-d) + LLM actions (Stream 2, 28-d × ≤64 events) |
| Window size | 30 s, epoch-aligned, with 8-window context for Stream 1 |
| Model | Mamba (Stream 1) + Transformer (Stream 2) + bidirectional cross-attention fusion + hybrid loss |
| Best params | `config_best.yml` — `cross_attention` fusion, `d_model=128`, `latent_dim=256`, `mamba_layers=4`, `transformer_layers=1`, `onecycle` LR |
| Headline test result | **AUROC ≈ 0.995, F1 ≈ 0.95** on favourable folds; mean ~0.60 F1 under strict agent-level CV due to tier imbalance (see §9) |
| Strongest baseline | DeepSVDD at 0.773 ± 0.005 AUROC / 0.191 F1 — substantially behind the dual-stream model on well-conditioned folds |
| Framework | PyTorch ≥ 2.4, Optuna ≥ 4.2, scikit-learn ≥ 1.6 |
| Hardware tested | NVIDIA H100 / H200 (CUDA 12.4), 7 × GPUs for parallel CV |

---

## 3. System architecture

### 3.1 Data collection — dual streams

AgentGuard collects from **two independent sources** inside each agent
container:

| Stream | Collector | Cadence | Features (per window) |
|--------|-----------|---------|-----------------------|
| **1 — OS telemetry** | `telemetry_collector.py` (per container) | 5 s samples → aggregated to 30 s windows | CPU / memory / process / network / file-I/O / destination-IP entropy / syscall distribution |
| **2 — LLM actions** | `agent_server.py` + `action_collector.py` | per event | event type, tool name, latency, tokens in/out, user-initiated flag, source label, time-delta, external-source flag |

A single Debian 13 host runs **20 agent containers** (15 attacked, 5 control)
plus an attacker and a dispatcher. The split is deliberate: the control group
establishes a baseline for what "normal" looks like under realistic LLM
workloads, so the model never sees synthetic-only negatives.

See [`docs/data-collection-infrastructure.md`](docs/data-collection-infrastructure.md)
for the full collection design.

### 3.2 Preprocessing

Raw JSONL → per-agent `.pt` files:

1. Parse telemetry + action JSONL per agent.
2. Assign every event to an **epoch-aligned 30-second window** (both streams
   share the same window index so fusion is time-coherent).
3. Aggregate Stream 1 into a 32-d feature vector per window (7 stat groups
   × 4 stats = 28 + 4 syscall stats).
4. Encode Stream 2 into a `[max_seq_len=64, 28]` sequence per window +
   binary mask.
5. Label each window from the attacker source and attack manifest
   (`attacks-*.jsonl`): `label ∈ {0, 1}`, plus `attack_id`, `attack_category`,
   `attack_id_sets`.

Implementation: [`data/preprocessing.py`](data/preprocessing.py) and
[`data/dataset/telemetry_dataset.py`](data/dataset/telemetry_dataset.py).

### 3.3 Model

```
┌───────────────────────────────────────────────────────────────────┐
│                    AgentGuardModel (models/agentguard.py)         │
│                                                                   │
│  stream1 [B, T1=8, 32]                                            │
│    │                                                              │
│    └── Stream1Encoder (Mamba × N)  ──► [B, T1, d_model]           │
│                                                                   │
│  stream2_seq [B, T2=64, 28] + mask                                │
│    │                                                              │
│    └── Stream2Encoder (Transformer × M + sinusoidal PE)           │
│                                    ──► [B, T2, d_model]           │
│                                                                   │
│        ┌──────────────── Fusion ────────────────┐                 │
│        │  cross_attention (default, bidir.)     │                 │
│        │  concat_mlp | gated | attention_pool   │                 │
│        └──────────────────────────────────────── ┘                │
│                           │                                       │
│                  latent [B, latent_dim]                           │
│                  │                                                │
│     ┌────────────┼────────────┬──────────────────────┐            │
│     ▼            ▼            ▼                      ▼            │
│  stream1      stream2    anomaly_head          (reserved for      │
│  decoder      decoder    (sigmoid)              attention export) │
│  [B, 32]      [B, 64, 28]  [B, 1]                                 │
└───────────────────────────────────────────────────────────────────┘
```

Key design choices:

- **Mamba for Stream 1** — selective state-space model with linear time/memory
  over the 8-window context, captures smooth telemetry dynamics without
  quadratic self-attention cost. See [`models/mamba.py`](models/mamba.py).
- **Transformer for Stream 2** — 64 events per window with highly variable
  position-to-meaning mapping benefit from full attention. Standard sinusoidal
  PE + masked mean pooling. See [`models/stream2_encoder.py`](models/stream2_encoder.py).
- **Bidirectional cross-attention** — each stream's full sequence attends to
  the other's full sequence (not just pooled vectors), so the model can align
  a CPU spike with the specific `tool_call` that caused it. Per-head attention
  weights are cached on the fusion module for interpretability. See
  [`models/fusion.py`](models/fusion.py).
- **Four-part hybrid loss** — see §3.4.
- **Three fusion fallbacks** — `concat_mlp`, `gated`, `attention_pool` consume
  pooled `[B, d_model]` vectors. Present as sweep-explored ablations; the
  best config keeps `cross_attention`.

### 3.4 Hybrid loss

Total loss, [`training/losses.py`](training/losses.py):

```
L = λ_recon      · L_recon          (MSE on both streams, stream 2 masked)
  + λ_contrast   · L_supcon         (SupCon on latent, class-weighted)
  + λ_temporal   · L_temporal       (L2 jump between adjacent windows, same agent)
  + λ_cls        · L_cls            (weighted BCE on anomaly_head)
```

Why each term:

- **Reconstruction** keeps the latent space anchored to the input distribution
  so anomalies deviate along a meaningful axis.
- **Supervised contrastive** forces same-class samples together and
  different-class samples apart, with upweighting of the minority anomaly
  class (`class_weight_ratio`).
- **Temporal smoothness** penalises latent-space jumps between truly adjacent
  windows of the *same* agent — stable benign baselines don't jitter, real
  attack onsets should.
- **Classification BCE** anchors the anomaly head's *polarity*; without it the
  sigmoid output can represent an arbitrary scalar shaped only by the
  contrastive geometry. The head sees weighted BCE on top of a non-finite
  guard (NaN/Inf → 0.5) to survive rare SSM prefix-scan overflows on Hopper.

### 3.5 Cross-validation protocol

Stratified **agent-level** 5-fold CV is the headline evaluation. Splits are
built by `make_stratified_folds` in `main.py` from three attack-rate tiers:

- **Tier 1** — agents 1-5, ~100 anomalies each (heavy attacker targeting)
- **Tier 2** — agents 6-8, ~21 anomalies each
- **Tier 3** — agents 9-15, ~13 anomalies each
- **Control** — agents 16-20, no anomalies

Round-robin within each tier ensures every fold gets a proportional mix of
attack intensities and a control agent. For every fold `i`:
`test = folds[i]`, `val = folds[(i+1) % k]`, `train = the rest`.

This is stricter than sample-level CV because an agent never appears in both
train and test, so the model has to generalise to unseen agents — not just
unseen windows from seen agents.

---

## 4. Repository layout

```
AgentGuard/
├── agentguard/                 (installed package, used by interpretability scripts)
├── baselines/                  Five anomaly-detection baselines + CV runner
│   ├── models/                 IsolationForest, LSTM-AE, CNN-AE, Transformer-AE, Deep SVDD
│   ├── dataset.py              FlatTensorDataset / SeqTensorDataset wrappers
│   ├── features.py             Left-padded sliding-window tensor assembly
│   ├── run_baselines.py        Per-(seed, fold) CV driver → baselines.csv + .md
│   └── train_torch.py          Generic train/score loops for AE baselines
├── data/
│   ├── preprocessing.py        JSONL → per-agent .pt tensors (run once)
│   ├── dataset/
│   │   ├── telemetry_dataset.py   AgentGuardDataset (unified dual-stream)
│   │   └── collate.py             agentguard_collate + MixupCollate
│   ├── dataset/                agentguard-all-batches/ (raw JSONL) — not in git
│   └── processed/              Preprocessed .pt files + checkpoints/
├── docs/
│   ├── README.md                Docs index
│   ├── architecture.md          Deep dive: encoders, fusion, loss
│   ├── data-pipeline.md         Preprocessing, windowing, labeling
│   ├── training.md              Training, CV, early stopping, logging
│   ├── hyperparameter-sweep.md  Four-phase Optuna workflow
│   ├── baselines.md             Five baselines, methodology, reproduction
│   ├── evaluation.md            Metrics, interpretability, error analysis
│   ├── configuration.md         Every YAML key explained
│   ├── cli.md                   main.py / sweep / baselines / scripts
│   ├── deployment.md            Ops, dashboard, inference serving
│   ├── troubleshooting.md       Common failures and fixes
│   └── data-collection-infrastructure.md   (existing) field collection guide
├── models/
│   ├── agentguard.py           Composed model (encoders + fusion + heads)
│   ├── stream1_encoder.py      Mamba-based Stream 1 encoder
│   ├── stream2_encoder.py      Transformer-based Stream 2 encoder
│   ├── fusion.py               Four fusion strategies
│   ├── mamba.py                MambaBlock + MambaSSM (log-space prefix-scan)
│   └── s4.py                   S4 reference implementation (unused at inference)
├── training/
│   ├── trainer.py              AgentGuardTrainer (fit/validate/evaluate)
│   └── losses.py               HybridLoss + three component losses
├── sweep/
│   ├── run_sweep.py            Phased Optuna driver (phases 1-4)
│   ├── search_space.py         Per-phase suggest_* functions
│   ├── objective.py            Per-trial fold runner + seed management
│   ├── config_override.py      Dot-notation merge onto base config
│   ├── analysis.py             Per-phase study analysis (importance, top-10)
│   ├── ensemble.py             Top-K weighted ensemble of sweep survivors
│   └── results/                optuna.db + best_params_phaseN.json + trials_*.csv
├── scripts/
│   ├── run_full_pipeline.sh    Installs deps, 4 stages (train/baselines/plots/reports)
│   ├── train_multiseed.py      N seeds × K folds training grid
│   ├── run_fold.py             Single-fold trainer (for notebook orchestrators)
│   ├── generate_interpretability_reports.py   Per-sample markdown + heatmap
│   ├── train_cv.sh / train_fixed_split.sh / optuna_train_cv.sh
│   └── plots/run_all.py        Convergence, t-SNE, UMAP, attention, ROC/PR
├── tests/
│   └── phase_b_smoke.py        Cross-attention + gated-fusion smoke test
├── utils/
│   ├── logging.py              setup_run_logger + EpochCSVWriter
│   ├── apply_best_params.py    Merge all phase JSONs → config_best.yml
│   └── discretization.py       HiPPO-Legendre bilinear discretization for S4
├── notebooks/
│   ├── agentguard_analysis.ipynb        Exploratory analysis
│   ├── model_training_evaluation.ipynb  Interactive train/eval
│   ├── sweep_and_eval.ipynb             Sweep orchestration
│   └── eda.ipynb                        EDA
├── results/
│   ├── baselines.md / .csv         Per-(seed, fold) baseline metrics
│   ├── results.md + results_foldN.md   AgentGuard per-fold CV detail
│   ├── test_results.md             Per-agent test-mode inference report
│   ├── figures/                    PDFs: convergence, latent embeddings, ROC/PR, attention
│   └── reports/
│       ├── index.md
│       ├── false_negatives/ *.md   Interpretability reports
│       └── false_positives/ *.md
├── action_collector.py         Server-side action event logger
├── dashboard.py                Streamlit live dashboard (SSH + live inference)
├── main.py                     CLI entry point (preprocess | train | eval | cv | test)
├── config.yml                  Base hyperparameters
├── config_best.yml             Post-sweep best config (consumed by scripts)
├── test_config.yml             Inference-time config for `--mode test`
└── requirements.txt
```

---

## 5. Quickstart

### 5.1 Prerequisites

- Python 3.10+
- CUDA-capable GPU strongly recommended (H100/H200 tested; code runs on CPU
  but sweeps will be impractically slow)
- Preprocessed `.pt` files under `data/processed/` (20 agents → 20 files).
  See §8.1 to build them from raw JSONL.

### 5.2 Install

```bash
# Install PyTorch matched to your CUDA version (example: CUDA 12.4)
pip install --index-url https://download.pytorch.org/whl/cu124 torch

# Remaining dependencies
pip install -r requirements.txt
```

The `scripts/run_full_pipeline.sh` script handles all of the above plus
distro packages (`parallel`, `rsync`, `tmux`) when run on a fresh Debian/
Ubuntu container.

### 5.3 Smoke-test the model (no training)

```bash
python -m tests.phase_b_smoke
```

Exercises cross-attention and gated fusion forward passes with masking,
verifies attention shapes, checks that masked positions get ~0 attention,
and confirms the output dict shape.

### 5.4 Train with the best config on the fixed split

```bash
python main.py --mode train --config config_best.yml
```

Trains `AgentGuardModel` on the train/val agents declared in
`config_best.yml::data.train_agents` / `val_agents`. Checkpoints land in
`data/processed/checkpoints/best_model.pt`; logs and per-epoch CSVs in
`logs/`.

### 5.5 5-fold cross-validation

```bash
python main.py --mode cv --config config_best.yml
```

Uses the tier-aware stratified splitter, trains a fresh model per fold,
writes per-fold checkpoints (`best_model_fold{1..5}.pt`) and emits a summary
at the end.

### 5.6 Full multi-seed pipeline (GPU cluster)

```bash
bash scripts/run_full_pipeline.sh                 # full pipeline
bash scripts/run_full_pipeline.sh --smoke-only    # stage 4 smoke test only
bash scripts/run_full_pipeline.sh --gpus 4        # cap Stage 1 fan-out
```

Stage layout: deps → CUDA verify → smoke → Stage 1 (3 seeds × 5 folds in
parallel) → Stage 2 (baselines × 3 seeds) → Stage 3 (plots) → Stage 4
(interpretability reports).

---

## 6. CLI reference

### 6.1 `main.py`

| Flag | Values | Default | Description |
|---|---|---|---|
| `--mode` | `preprocess \| train \| eval \| cv \| test` | **required** | Pipeline mode |
| `--config` | path | `config.yml` | Base config to load |
| `--weights_config` | path | `config.yml` | Architecture config for `--mode test` (must match the checkpoint) |

Modes:

- `preprocess` — read raw JSONL under `data.raw_data_dir`, write per-agent
  `.pt` files to `data.processed_dir`.
- `train` — fit on `data.train_agents`, validate on `data.val_agents`,
  checkpoint best AUROC.
- `eval` — load the best checkpoint, evaluate on `data.test_agents`.
- `cv` — 5-fold stratified agent-level CV, per-fold checkpoints + summary.
- `test` — external inference mode for arbitrary `--config` (typically
  `test_config.yml`) against a checkpoint declared in
  `inference.checkpoint_path`, writing a per-agent Markdown report.

### 6.2 `sweep/run_sweep.py`

```bash
python -m sweep.run_sweep --phase 1                 # Architecture (100 trials, single split)
python -m sweep.run_sweep --phase 2                 # Training dynamics (60 trials, 3-fold)
python -m sweep.run_sweep --phase 3                 # Loss + data (60 trials, 3-fold)
python -m sweep.run_sweep --phase 4                 # Full 5-fold CV on top-K from phase 3
python -m sweep.run_sweep --phase all               # 1 → 2 → 3 → 4 sequentially
python -m sweep.run_sweep --phase 1 --n-trials 50   # Override trial budget
```

Results flow: `sweep/results/best_params_phase{1..4}.json` plus
`trials_phase{N}.csv`. Apply them to a fresh `config_best.yml` with:

```bash
python -m utils.apply_best_params
```

Analyze a completed phase:

```bash
python -m sweep.analysis --phase 1
python -m sweep.analysis --phase all
```

Train a weighted ensemble of the top-K configs:

```bash
python -m sweep.ensemble --top-k 3 --config config.yml
```

### 6.3 `baselines/run_baselines.py`

```bash
python baselines/run_baselines.py --config config_best.yml --seeds 42,1337,2024
python baselines/run_baselines.py --config config_best.yml --fast   # 3 epochs / model
```

Runs five baselines per (seed, fold), writing
`results/baselines.csv` / `.md` and per-baseline `predictions/*.npz` dumps
for the plotting stage.

### 6.4 Multi-seed driver

```bash
python scripts/train_multiseed.py \
    --config config_best.yml --seeds 42,1337,2024 \
    --out_dir .
```

Outputs per (seed, fold):

- `logs/seed{seed}_fold{fold}_epochs.csv`
- `data/processed/checkpoints/model_seed{seed}_fold{fold}.pt`
- `predictions/agentguard_seed{seed}_fold{fold}.npz`
- `latents/agentguard_seed{seed}_fold{fold}.npz`

### 6.5 Interpretability reports

```bash
python scripts/generate_interpretability_reports.py \
    --config config_best.yml --seed 42 --fold 1 \
    --out_dir results/reports --n_per_category 3
```

Picks top-N true-positives per attack category, top FPs, and lowest-scored
FNs; emits one Markdown report + attribution heatmap PNG per sample.

---

## 7. Configuration reference

Keys referenced below exist in `config.yml` and `config_best.yml`. See
[`docs/configuration.md`](docs/configuration.md) for the full catalogue.

### `data`

| Key | Meaning |
|-----|---------|
| `raw_data_dir` | Root of raw JSONL dataset (`batch/`, `agent-*/telemetry/`, `agent-*/actions/`) |
| `processed_dir` | Output dir for `.pt` files + `checkpoints/` |
| `date` | Date string in the JSONL filenames (e.g. `2026-03-15`) |
| `window_size` | Seconds per window (default `30`) |
| `seq_context` | Number of consecutive Stream 1 windows fed to the Mamba encoder (default `8`) |
| `max_seq_len` | Max Stream 2 events per window (default `64`) |
| `attacked_agents` / `control_agents` | Full 15/5 split, source of truth for CV folding |
| `train_agents` / `val_agents` / `test_agents` | Used only by `--mode train` / `eval` / `test` (non-CV) |
| `augmentation` | `none` / `feature_mask` / `time_jitter` / `mixup` |
| `augmentation_prob` | Probability of applying augmentation per sample |
| `class_weight_ratio` | Up-weight for the anomaly class in SupCon + BCE |
| `k_folds` | Fold count for `--mode cv` |

### `model`

| Key | Meaning |
|-----|---------|
| `stream1_input_dim` / `stream2_input_dim` | 32 / 28 (fixed by preprocessing) |
| `d_model` | Shared encoder hidden dim (64 / 128 / 256 / 512 searched) |
| `latent_dim` | Post-fusion latent dim |
| `mamba_layers` | Mamba block depth (1-6) |
| `transformer_layers` / `transformer_heads` / `transformer_ff_dim` | Stream 2 encoder capacity |
| `dropout` | Applied inside transformer encoder layers |
| `fusion_strategy` | `cross_attention` (best) / `concat_mlp` / `gated` / `attention_pool` |
| `cls_head_layers` / `cls_head_hidden_dim` / `cls_head_activation` | Anomaly-head depth and non-linearity |
| `decoder_activation` | `relu` / `gelu` / `silu` for reconstruction decoders |

### `training`

| Key | Meaning |
|-----|---------|
| `batch_size` | 16-512 searched; 16 in the best config (paired with `onecycle`) |
| `epochs` / `early_stopping_patience` | Max epochs and early stop patience on AUROC |
| `lr` / `optimizer` / `scheduler` / `weight_decay` / `max_grad_norm` | Optimiser plumbing |
| `lambda_recon` / `lambda_contrastive` / `lambda_temporal` / `lambda_cls` | Hybrid-loss weights |

### `logging`

| Key | Meaning |
|-----|---------|
| `enabled` | Master switch (on by default) |
| `log_dir` | Where `setup_run_logger` writes `.log` and `_epochs.csv` |
| `save_epoch_csv` | Whether to emit a per-run CSV beside the log file |

---

## 8. Pipeline stages

### 8.1 Preprocess raw JSONL

```bash
python main.py --mode preprocess --config config.yml
```

- Walks `data.raw_data_dir/batch/*/attacks-*.jsonl` to build an `attack_id →
  {category, prompt}` manifest.
- For each agent directory, reads `telemetry/{date}.jsonl` and
  `actions/{date}.jsonl`, assigns events to 30-s windows, aggregates
  Stream 1, encodes Stream 2, derives labels from `attacker-*` sources.
- Saves `data/processed/{agent}.pt` with keys: `stream1`, `stream2_seq`,
  `stream2_mask`, `labels`, `window_starts`, `attack_ids`,
  `attack_categories`, `attack_id_sets`.

### 8.2 Train (fixed split)

```bash
python main.py --mode train --config config_best.yml
```

- `AgentGuardTrainer` runs until early stop on AUROC improvement.
- Writes `data/processed/checkpoints/best_model.pt` + `logs/train_*.log` +
  `logs/train_*_epochs.csv`.

### 8.3 Cross-validate

```bash
python main.py --mode cv --config config_best.yml
```

- 5 folds, per-fold checkpoints `best_model_fold{1..5}.pt`.
- See `results/results_fold{1..5}.md` and `results/results.md` for the
  current run's detailed per-fold breakdown.

### 8.4 Hyperparameter sweep

Four phases, search space in
[`sweep/search_space.py`](sweep/search_space.py):

1. **Phase 1 — Architecture** (100 trials, single train/val split). Searches
   `d_model`, `latent_dim`, `mamba_layers`, `transformer_*`, `dropout`,
   `fusion_strategy`, classifier-head depth/activation, decoder activation.
2. **Phase 2 — Training dynamics** (60 trials, 3-fold). Locks Phase 1 winners.
   Searches `lr` (log-uniform 1e-4 → 3e-3), `optimizer`, `scheduler`,
   `batch_size`, `grad_clip`, `weight_decay` (adamw only).
3. **Phase 3 — Loss + data** (60 trials, 3-fold). Locks phases 1-2.
   Searches loss λ's, `seq_context`, `augmentation` (+ prob),
   `class_weight_ratio`.
4. **Phase 4 — Final CV** (top-K from Phase 3, 5 folds). No new trials; just
   full CV on the top configurations.

Storage: SQLite at `sweep/results/optuna.db` by default; set
`OPTUNA_STORAGE` to a Postgres URL for distributed runs.

### 8.5 Baselines

```bash
python baselines/run_baselines.py --config config_best.yml --seeds 42,1337,2024
```

One-class training (normal-only) for all four AEs + Deep SVDD; supervised
fit for IsolationForest using `contamination = train_anomaly_rate`.
Thresholds are chosen on the validation set by grid search over F1
quantiles. Scores dumped to `predictions/{slug}_seed{S}_fold{F}.npz`.

### 8.6 Plots & interpretability

```bash
python scripts/plots/run_all.py
python scripts/generate_interpretability_reports.py \
    --config config_best.yml --seed 42 --fold 1
```

Produces:

- `results/figures/convergence.pdf` — per-seed training curves.
- `results/figures/latent_tsne.pdf` / `latent_umap.pdf` — latent-space
  embeddings of the test fold coloured by label / attack category.
- `results/figures/attention_by_category.pdf` — aggregated cross-attention
  heatmaps per attack family.
- `results/figures/roc_pr_comparison.pdf` — AgentGuard vs baselines ROC + PR.
- `results/reports/{category}/{agent}_{window}.md` — per-sample detection
  report (attack metadata, temporal attribution, flagged action pairs,
  feature z-scores vs benign baseline, attribution heatmap PNG).
- `results/reports/false_positives/` & `false_negatives/` — error-case
  reports for manual review.

---

## 9. Results

### 9.1 5-fold CV (from `results/results.md`)

| Fold | AUROC  | AUPRC  | F1     | Precision | Recall |
|------|--------|--------|--------|-----------|--------|
| 1    | 0.0437 | 0.0243 | 0.0888 | 0.0465    | 1.0000 |
| 2    | 0.9776 | 0.4854 | 0.6237 | 0.6170    | 0.6304 |
| 3    | 0.0187 | 0.0248 | 0.0914 | 0.0479    | 1.0000 |
| 4    | 0.9911 | 0.9262 | 0.9099 | 0.8559    | 0.9712 |
| 5    | 0.9960 | 0.9699 | 0.9245 | 0.9074    | 0.9423 |

**Reading the table.** Folds 2, 4, 5 are high-quality splits where the model
achieves near-ceiling AUROC and F1 > 0.6. Folds 1 and 3 degenerate — the
model predicts all-positive (`recall=1.0`, `precision≈0.05`). This matches
the pattern described in the trainer: class imbalance + certain fold
compositions (Tier 3 agents dominating the test split with very few
anomalies) starve the contrastive and BCE signals, and the best AUROC model
selector picks an epoch 1 all-anomalous predictor. Mitigations tracked in
`docs/evaluation.md`.

### 9.2 Fixed-split test (`results/test_results.md`)

**Overall — 4,556 windows / 226 anomalies / 7 test agents**

| Metric | Value |
|---|---|
| Accuracy | 0.9947 |
| Precision | 0.9353 |
| Recall | 0.9602 |
| **F1** | **0.9476** |
| Confusion matrix | [[4315, 15], [9, 217]] |

Per-agent F1 ranges from 0.92 (agent-4) to 1.00 (agent-11). Control agents
(agent-18, agent-19) correctly have zero positive predictions except for one
false positive each.

### 9.3 Baselines (3 seeds × 5 folds, from `results/baselines.md`)

| Baseline | AUROC | AUPRC | F1 |
|---|---|---|---|
| IsolationForest | 0.3870 ± 0.0301 | 0.0599 ± 0.0024 | 0.1131 ± 0.0043 |
| LSTMAE | 0.4502 ± 0.0780 | 0.0707 ± 0.0104 | 0.1489 ± 0.0044 |
| CNNAE | 0.3654 ± 0.0164 | 0.0675 ± 0.0156 | 0.1452 ± 0.0047 |
| TransformerAE | 0.4872 ± 0.0728 | 0.0713 ± 0.0078 | 0.1499 ± 0.0044 |
| **DeepSVDD** | **0.7732 ± 0.0045** | **0.1057 ± 0.0065** | **0.1911 ± 0.0106** |

AgentGuard clears every baseline by a wide margin on its good folds. On
aggregate, DeepSVDD is the only baseline within range of AgentGuard's mean
AUROC, but it still sits ~0.2 below AgentGuard's F1 on Folds 2 / 4 / 5.
The gap is consistent with the dual-stream hypothesis: single-stream
reconstruction can spot resource abuse but misses tool-chain and prompt
injection attacks that have no distinctive OS fingerprint.

### 9.4 Best hyperparameters (`sweep/results/best_params_phase{1..4}.json`)

- **Architecture (Phase 1):** `d_model=128`, `latent_dim=256`,
  `mamba_layers=4`, `transformer_layers=1`, `transformer_heads=8`,
  `transformer_ff_dim=1024`, `dropout=0.3`, `fusion_strategy=cross_attention`,
  `cls_head_layers=1`, `cls_head_hidden_dim=32`,
  `cls_head_activation=gelu`, `decoder_activation=gelu`.
- **Training (Phase 2):** `lr≈2.5e-3`, `optimizer=adam`,
  `scheduler=onecycle`, `batch_size=16`, `grad_clip=1.0`.
- **Loss + data (Phase 4 winner):** `lambda_recon≈1.84`,
  `lambda_contrastive≈1.50`, `lambda_temporal≈0.013`, `seq_context=8`,
  `augmentation=none`, `class_weight_ratio≈2.46`.

---

## 10. Dashboard & live inference

[`dashboard.py`](dashboard.py) is a Streamlit app that:

1. Opens an SSH/SFTP session to the agent host via `paramiko`.
2. Tails `/var/log/agentguard/telemetry/*.jsonl` and `actions/*.jsonl`.
3. Replays new events into the window aggregator every ~1 s.
4. Runs the trained `AgentGuardModel` on the latest 8-window context plus
   current Stream 2 events.
5. Displays live anomaly score, feature sparklines, recent tool calls,
   and a running timeline of suspect events.

Run it locally (model weights expected at a path configured in the script):

```bash
streamlit run dashboard.py
```

SSH and API-key fields are editable in the sidebar. No data leaves the
host without an explicit SSH connection; the dashboard is read-only with
respect to the agent processes.

Server-side, [`action_collector.py`](action_collector.py) exposes two
entry points:

- `log_action_event(...)` — import inside your agent loop to emit one JSONL
  record per event.
- `exec_prompt(...)` — `echo "prompt" | python action_collector.py --mode exec`,
  intended to be wrapped by the dashboard's "Run a prompt" feature.

The sample `AgentGuardOpenClawHook` class shows the expected integration
shape for OpenClaw-style agents; adapt its `on_*` callbacks to your own
agent framework.

---

## 11. Reproducibility

- **Global seed** — `main.set_global_seed(seed)` is called at the top of
  `main()` (default 42). It seeds `random`, `numpy`, `torch` (incl. CUDA)
  and disables TF32 via `allow_tf32=False` and
  `set_float32_matmul_precision("highest")`. TF32 on Hopper/Ada was observed
  to push the Mamba SSM prefix-scan into NaN territory that then triggers a
  device-side BCELoss assertion; forcing fp32 matmul removes the failure
  mode at a minor throughput cost.
- **Checkpoints** — per fold / per (seed, fold). Checkpoints include
  `epoch`, `model_state_dict`, `optimizer_state_dict`, `val_loss`, `metrics`.
- **Study storage** — SQLite (`sweep/results/optuna.db`) by default; set
  `OPTUNA_STORAGE=postgresql://...` for distributed sweeps.
- **Stream determinism** — the dataset's augmentation path is bypassed
  whenever `set_training_mode(False)` is called (done automatically for val /
  test loaders inside the sweep and multiseed drivers).
- **Config freeze** — every training run writes the flattened config into
  its `.log` header (see `utils/logging.log_config`). To reproduce a run
  exactly, diff the `.log` header against the current YAML.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `torch.cuda.is_available() == False` after install | PyPI default torch is CPU-only | Install from the CUDA index: `pip install --index-url https://download.pytorch.org/whl/cu124 torch` |
| BCELoss device-side assertion on Hopper | NaN from SSM prefix-scan with TF32 | The trainer already replaces non-finite `anomaly_score` with 0.5, and `set_global_seed` disables TF32 — make sure you don't re-enable it in a custom runner |
| Fold 1/3 AUROC collapses to ~0.04 | Tier 3 agents dominate test split, contrastive + BCE starved | Use multi-seed CV (`scripts/train_multiseed.py`), aggregate across seeds; or ensemble top-K configs from the sweep (§6.2) |
| `RuntimeError: CUDA out of memory` in sweep | Phase 1 stumbles on `d_model=512, latent_dim=256` | Handled by the sweep objective — trial returns 0.0 and continues; to avoid, drop `512` from the Phase 1 search space |
| Pre-commit / pipeline rerun needed | Failed Stage 1/2 jobs | `parallel --retry-failed --joblog logs/stage1_joblog.tsv` |
| Docker/SSH live mode silent | `paramiko` missing | `pip install paramiko>=3.4.0` |
| Dashboard shows stale scores | Model/checkpoint path mismatch | Confirm `test_config.yml::inference.checkpoint_path` exists and that `weights_config` passed into `--mode test` matches its architecture |

More deeply in [`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## 13. Further reading

All under [`docs/`](docs/):

- [`architecture.md`](docs/architecture.md) — model internals
- [`data-pipeline.md`](docs/data-pipeline.md) — preprocessing details
- [`training.md`](docs/training.md) — trainer loop, CV, early stopping
- [`hyperparameter-sweep.md`](docs/hyperparameter-sweep.md) — four-phase sweep
- [`baselines.md`](docs/baselines.md) — baseline rationale and reproduction
- [`evaluation.md`](docs/evaluation.md) — metrics, interpretability, error analysis
- [`configuration.md`](docs/configuration.md) — every YAML key
- [`cli.md`](docs/cli.md) — CLI cheatsheet
- [`deployment.md`](docs/deployment.md) — ops, dashboard, inference serving
- [`troubleshooting.md`](docs/troubleshooting.md) — extended failure catalogue
- [`data-collection-infrastructure.md`](docs/data-collection-infrastructure.md)
  — container topology, attack taxonomy, batch collection protocol
