# Configuration reference

Every key in `config.yml`, `config_best.yml`, and `test_config.yml`,
grouped by top-level section. All YAML files deep-merge with dot-notation
overrides from the sweep — see
[`sweep/config_override.py`](../sweep/config_override.py).

---

## 1. File roles

| File | Consumers | Purpose |
|---|---|---|
| `config.yml` | default for `main.py --mode train/eval/cv`, `python -m sweep.run_sweep`, baselines | Hand-written baseline configuration |
| `config_best.yml` | `scripts/run_full_pipeline.sh`, `scripts/train_multiseed.py`, interpretability driver | Post-sweep winner; overwritten by `python -m utils.apply_best_params` |
| `test_config.yml` | `main.py --mode test` | Minimal inference-only config pointing to a checkpoint + test agents |

Setting `--config` on the CLI selects the "main" config; inference mode
additionally takes `--weights_config` for the architecture that matches
the checkpoint.

---

## 2. `data`

| Key | Type | Typical | Notes |
|-----|------|---------|-------|
| `raw_data_dir` | path | `data/dataset/agentguard-all-batches` | Root of raw JSONL (`agent-*/telemetry/`, `agent-*/actions/`, `batch/*/attacks-*.jsonl`). Consumed by `--mode preprocess`. |
| `processed_dir` | path | `data/processed` | Where per-agent `.pt` files live and where `checkpoints/` are written. |
| `date` | string | `2026-03-15` | Date component of the raw JSONL filenames. |
| `window_size` | int (s) | `30` | Seconds per window. **Changing this requires re-preprocessing.** |
| `seq_context` | int | `8` | Stream 1 context length (number of consecutive windows fed to Mamba). Must be ≥1. Sweep searched {4, 8, 16}. |
| `max_seq_len` | int | `64` | Max Stream 2 events per window. **Changing this requires re-preprocessing.** |
| `attacked_agents` | list[str] | `agent-1..agent-15` | Full attacked-agent set. Used by the stratified folder. |
| `control_agents` | list[str] | `agent-16..agent-20` | Full control-agent set. |
| `train_agents` / `val_agents` / `test_agents` | list[str] | subset | Used only by `--mode train/eval/test` (non-CV). CV ignores these and derives splits from `attacked_agents` + `control_agents`. |
| `augmentation` | `none` / `feature_mask` / `time_jitter` / `mixup` | `none` | Stream-1+2 augmentation strategy. `mixup` also needs `MixupCollate`. |
| `augmentation_prob` | float | `0.0` | Per-sample apply probability (ignored for `none`). |
| `class_weight_ratio` | float | `~2.46` | Up-weight for the anomaly class in SupCon and BCE. |
| `k_folds` | int | `5` | CV fold count. Changing requires re-running `--mode cv`. |

---

## 3. `model`

| Key | Type | Typical | Notes |
|-----|------|---------|-------|
| `stream1_input_dim` | int | `32` | Fixed by preprocessing — do not change without re-preprocessing. |
| `stream2_input_dim` | int | `28` | Same. |
| `d_model` | int | `128` | Encoder hidden dim. Shared by Mamba, Transformer, and fusion. |
| `latent_dim` | int | `256` | Post-fusion latent dim; feeds reconstructions and the anomaly head. |
| `mamba_layers` | int | `4` | Mamba block depth (1-6 searched). |
| `transformer_layers` | int | `1` | Transformer encoder depth (1-6 searched; 1 won). |
| `transformer_heads` | int | `8` | Attention heads; must divide `d_model`. |
| `transformer_ff_dim` | int | `1024` | FF hidden inside the transformer encoder layer. |
| `dropout` | float | `0.3` | Dropout inside TransformerEncoderLayer. |
| `fusion_strategy` | enum | `cross_attention` | `cross_attention`, `concat_mlp`, `gated`, `attention_pool`. |
| `cls_head_layers` | int ∈ {1,2,3} | `1` | Anomaly head depth; 1 = `Linear → Sigmoid`. |
| `cls_head_hidden_dim` | int | `32` | Hidden dim for multi-layer heads (ignored for layers=1). |
| `cls_head_activation` | `relu` / `gelu` / `silu` | `gelu` | Activation between head layers. |
| `decoder_activation` | `relu` / `gelu` / `silu` | `gelu` | Activation inside the reconstruction decoders. |

Note: the trainer also references `model.mamba_state_dim` in `main.build_model`
but the default (`mamba_state_dim = d_model`) is hard-coded there; expose
it in YAML only if the sweep adds a dedicated axis.

---

## 4. `training`

| Key | Type | Typical | Notes |
|-----|------|---------|-------|
| `batch_size` | int | `16` | Smaller batches + `onecycle` beat large batches in sweep. |
| `epochs` | int | `100-150` | Upper bound. Early stop usually triggers before this. |
| `early_stopping_patience` | int | `10-20` | Epochs without AUROC improvement before stopping. |
| `lr` | float | `~2.5e-3` | Peak LR under `onecycle`; base LR under `cosine` / `plateau`. |
| `optimizer` | `adam` / `adamw` | `adam` | `adamw` also requires `weight_decay`. |
| `weight_decay` | float | `~8.5e-5` | Applied by `adamw` only. |
| `scheduler` | `cosine` / `plateau` / `onecycle` | `onecycle` | `onecycle` steps per batch; others per epoch. |
| `max_grad_norm` | float | `1.0` | `nn.utils.clip_grad_norm_` before each `optimizer.step()`. |
| `lambda_recon` | float | `~1.84` | Weight for `L_recon` (MSE both streams). |
| `lambda_contrastive` | float | `~1.50` | Weight for SupCon loss on latent. |
| `lambda_temporal` | float | `~0.013` | Weight for adjacent-window L2 smoothness. |
| `lambda_cls` | float | `1.0` | Weight for weighted BCE on the anomaly head. Not currently in the sweep. |

### 4.1 Scheduler behaviour

- **`cosine`**: `CosineAnnealingLR(T_max=epochs)`. Per-epoch step. Good
  for stable configs that reach a plateau.
- **`plateau`**: `ReduceLROnPlateau(mode="min", patience=5, factor=0.5)`.
  Per-epoch step; fed `val_losses["total"]`. Useful when loss
  trajectories are noisy.
- **`onecycle`**: `OneCycleLR(max_lr=lr, total_steps=epochs * len(train_loader))`.
  Per-batch step. The sweep winner; pairs with small batches.

---

## 5. `logging`

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `enabled` | bool | `true` | Master switch for file logging. Stdout is unaffected. |
| `log_dir` | path | `logs` | Created on first run. |
| `save_epoch_csv` | bool | `true` | Emit a per-epoch CSV next to each `.log`. |

The logger filename encodes mode + (optional) phase + (optional) trial
number + timestamp, e.g. `sweep_phase1_t045_20260315_121004.log`.

---

## 6. `inference` (test_config.yml only)

| Key | Type | Notes |
|-----|------|-------|
| `checkpoint_path` | path | `.pt` produced by training (contains `model_state_dict` + optimizer state + metrics). |
| `batch_size` | int | Batch size for inference DataLoader. |

Additionally, `experiment.name` and `experiment.seed` are read at the top
of `test_config.yml` for traceability but aren't strictly required by the
runtime.

---

## 7. Dot-notation overrides

The sweep uses dot-notation overrides to apply layered best-params without
touching the YAML. Example:

```python
override_config(base_config, {
    "model.d_model": 256,
    "model.mamba_layers": 4,
    "training.lr": 1e-3,
})
```

Implementation: [`sweep/config_override.py`](../sweep/config_override.py).
Deep-merges onto a deepcopy so the original stays intact.

`utils.apply_best_params` uses the non-dotted form — it assumes best
params JSON keys match known YAML keys and walks `config["model"]`,
`config["training"]`, `config["data"]` looking for each.

---

## 8. Example: deriving `config_best.yml`

```bash
# 1. Run all sweep phases (or load pre-computed best_params JSONs)
python -m sweep.run_sweep --phase all

# 2. Apply all four phase JSONs to config.yml, write config_best.yml
python -m utils.apply_best_params

# 3. Inspect / edit by hand if needed (e.g., bump epochs for final run)
vim config_best.yml

# 4. Train with it
python main.py --mode train --config config_best.yml
```

The generated `config_best.yml` merges all phase JSONs in order; a
warning is printed for any key that doesn't match a known config section.
