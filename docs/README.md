# AgentGuard documentation

The full set of long-form docs for this repository. The root
[`README.md`](../README.md) is the top-level entry point; this folder
contains the deep dives.

---

## Reading order

If you're new to the project, read in this order:

1. **[`data-collection-infrastructure.md`](./data-collection-infrastructure.md)**
   — how the dataset is generated: container topology, dual streams,
   attack taxonomy, batch collection protocol.
2. **[`data-pipeline.md`](./data-pipeline.md)** — JSONL → `.pt` tensors:
   windowing, feature encoding, labeling, normalization, augmentation.
3. **[`architecture.md`](./architecture.md)** — the model itself: Mamba
   Stream 1 encoder, Transformer Stream 2 encoder, cross-attention
   fusion, reconstruction + classification heads, design rationale.
4. **[`training.md`](./training.md)** — trainer loop, hybrid loss,
   cross-validation protocol, multi-seed, logging, reproducibility.
5. **[`hyperparameter-sweep.md`](./hyperparameter-sweep.md)** — four-phase
   Optuna workflow, search spaces, post-sweep analysis, ensemble.
6. **[`baselines.md`](./baselines.md)** — Isolation Forest, LSTM-AE,
   CNN-AE, Transformer-AE, Deep SVDD: implementations and reproduction.
7. **[`evaluation.md`](./evaluation.md)** — metrics, thresholding,
   attention visualisation, interpretability reports, error analysis.
8. **[`configuration.md`](./configuration.md)** — every YAML key
   explained, role of `config.yml` vs `config_best.yml` vs
   `test_config.yml`, dot-notation overrides.
9. **[`cli.md`](./cli.md)** — CLI cheat sheet for every entry point.
10. **[`deployment.md`](./deployment.md)** — dashboard, live inference,
    SSH contract, alerting, security hardening.
11. **[`troubleshooting.md`](./troubleshooting.md)** — known failure
    modes and fixes.

---

## Index by topic

### Model

- [`architecture.md`](./architecture.md)
- [`models/agentguard.py`](../models/agentguard.py)
- [`models/stream1_encoder.py`](../models/stream1_encoder.py)
- [`models/stream2_encoder.py`](../models/stream2_encoder.py)
- [`models/fusion.py`](../models/fusion.py)
- [`models/mamba.py`](../models/mamba.py)

### Data

- [`data-pipeline.md`](./data-pipeline.md)
- [`data-collection-infrastructure.md`](./data-collection-infrastructure.md)
- [`data/preprocessing.py`](../data/preprocessing.py)
- [`data/dataset/telemetry_dataset.py`](../data/dataset/telemetry_dataset.py)

### Training

- [`training.md`](./training.md)
- [`training/trainer.py`](../training/trainer.py)
- [`training/losses.py`](../training/losses.py)

### Sweep

- [`hyperparameter-sweep.md`](./hyperparameter-sweep.md)
- [`sweep/run_sweep.py`](../sweep/run_sweep.py)
- [`sweep/search_space.py`](../sweep/search_space.py)
- [`sweep/objective.py`](../sweep/objective.py)
- [`sweep/analysis.py`](../sweep/analysis.py)
- [`sweep/ensemble.py`](../sweep/ensemble.py)

### Baselines

- [`baselines.md`](./baselines.md)
- [`baselines/run_baselines.py`](../baselines/run_baselines.py)
- [`baselines/models/`](../baselines/models/)

### Evaluation

- [`evaluation.md`](./evaluation.md)
- [`results/`](../results/)
- [`scripts/generate_interpretability_reports.py`](../scripts/generate_interpretability_reports.py)
- [`scripts/plots/run_all.py`](../scripts/plots/run_all.py)

### Ops

- [`deployment.md`](./deployment.md)
- [`troubleshooting.md`](./troubleshooting.md)
- [`dashboard.py`](../dashboard.py)
- [`action_collector.py`](../action_collector.py)
- [`scripts/run_full_pipeline.sh`](../scripts/run_full_pipeline.sh)

### Configuration

- [`configuration.md`](./configuration.md)
- [`cli.md`](./cli.md)
- [`config.yml`](../config.yml)
- [`config_best.yml`](../config_best.yml)
- [`test_config.yml`](../test_config.yml)

---

## Document status

All pages listed above are kept in sync with the code at
[`master`](../) HEAD. When making significant code changes, update the
relevant doc in the same PR so this set stays the source of truth for
design intent and operational knowledge.

---

## Conventions

- Paths are relative to the repo root.
- Bash examples assume you run from the repo root.
- Config keys are written in dot notation (`data.window_size`,
  `training.lr`) to match the sweep's override format.
- Status indicators when used: ✅ complete / implemented,
  ⚠️ partial / known issue, ❌ not supported.

---

## Contributing to the docs

When adding new functionality:

1. Edit the relevant deep-dive file (not the README) with the technical
   detail.
2. Cross-link from the README's §13 "Further reading" if the topic is new.
3. Update `configuration.md` if you added / renamed a YAML key.
4. Add a CLI entry to `cli.md` if you added a new entry point.
5. If you introduced a new failure mode, add a row to
   `troubleshooting.md`.

Keep examples runnable (copy-paste from the repo root) and keep metric
numbers consistent with the current `results/`.
