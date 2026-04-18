# Model Architecture

This document is a technical deep-dive into the AgentGuard model. The paired
overview in the [README §3](../README.md#3-system-architecture) covers the
shape of the system; this page covers the *why* and the *how* of each block.

---

## 1. Design goals

1. **Dual-stream primacy.** Never collapse the two input streams into a shared
   feature space before each has its own sequence model. OS telemetry and
   LLM action logs are different modalities (continuous dense vs discrete
   sparse) with different temporal statistics; premature fusion destroys
   information that either stream alone makes use of.
2. **Temporal resolution per modality.**
   - Stream 1 is dense, low-entropy, regularly sampled → Mamba (linear in
     sequence length; pre-ordains smooth state dynamics).
   - Stream 2 is sparse, bursty, variable-length → Transformer (full
     attention; short sequences of ≤64 keep cost manageable).
3. **Explicit cross-modal alignment.** Fusion is where the dual-stream
   hypothesis is tested. Bidirectional cross-attention on the full encoder
   sequences (not pooled vectors) is the strongest form; three weaker
   variants are kept for ablation and sweep-time exploration.
4. **Multiple objectives, not one.** Reconstruction pins the latent to the
   input manifold; contrastive shapes the latent geometry around the binary
   label; temporal smoothness suppresses spurious window-to-window jitter;
   BCE anchors the anomaly-head polarity.
5. **Production stability.** Numerical safeguards (log-space prefix scan,
   `_safe_key_padding_mask`, BCE NaN guard, TF32 disable) ensure runs don't
   silently degrade on newer GPUs.

---

## 2. Stream 1 encoder — Mamba

File: [`models/stream1_encoder.py`](../models/stream1_encoder.py),
[`models/mamba.py`](../models/mamba.py).

### 2.1 Block

```
Input [B, seq_context=8, 32]
  │
  └── Linear(32, d_model)
         │
         ├── MambaBlock (× n_layers)  —— residual + LayerNorm
         │     ├── in_proj: Linear(d_model → 2·d_model)
         │     ├── split into (x_ssm, x_gate)
         │     ├── x_ssm: Conv1d(kernel_size=3) → SiLU → MambaSSM
         │     ├── x_gate: SiLU
         │     └── out_proj(Linear) on (ssm_out * gate)
         │
         └── Output
               • return_sequence=False → [B, d_model] (last timestep)
               • return_sequence=True  → [B, seq_context, d_model] (for cross-attention)
```

### 2.2 MambaSSM (selective state-space)

Implements the Mamba selective SSM of Gu & Dao (2023):

- Diagonal state matrix `A` initialized as `-|N(0,1)|` (negative → stable
  decay).
- Dynamic `B(u)`, `C(u)`, `δ(u)` via three linear projections.
- `A_discrete = exp(δ ⊙ A).clamp(-15, 15)` for numerical safety.
- **Log-space prefix scan** — `log_A.cumsum` → `exp` (clamped) rather than
  direct cumulative product; keeps precision across long sequences.
- Output `y = C(u) ⊙ x_t`, where `x_t = A_prefix · cumsum(B·input / A_prefix)`
  — linear-time selective convolution.

### 2.3 Why not a Transformer for Stream 1?

- `seq_context=8` is short, but Stream 1 is *smooth* — a full attention
  mechanism overfits to spurious tokens in training and regularises worse.
- Mamba's continuous-time bias matches the physical interpretation of
  telemetry: CPU and memory don't teleport; they evolve.
- Linear-in-T cost matters when this runs live in the dashboard at 1 Hz
  against a rolling buffer.

---

## 3. Stream 2 encoder — Transformer

File: [`models/stream2_encoder.py`](../models/stream2_encoder.py).

### 3.1 Block

```
Input [B, 64, 28] + mask [B, 64]  (1 = real, 0 = pad)
  │
  ├── Linear(28, d_model)
  ├── SinusoidalPositionalEncoding (max_len=64)
  │
  ├── TransformerEncoder × n_layers
  │     (batch_first=True, src_key_padding_mask from inverted mask)
  │
  └── Output
        • return_sequence=False → masked mean pool → [B, d_model]
        • return_sequence=True  → [B, 64, d_model] (for cross-attention)
```

### 3.2 Why sinusoidal PE

Learned positional embeddings were tried during sweep but did not improve on
sinusoidal — the variability of action-sequence lengths (0-64 real events
per window) means fixed tables don't specialise to any particular length.

### 3.3 Masked mean pooling

```python
mask_expanded = mask.unsqueeze(-1)                 # [B, T, 1]
x = (x * mask_expanded).sum(dim=1) / mask_expanded.sum(dim=1).clamp(min=1)
```

`clamp(min=1)` guards against all-pad windows (benign windows with no action
events). The cross-attention path uses `_safe_key_padding_mask` for the same
failure mode (see §4.3).

### 3.4 Input feature encoding (28 dims)

Set in `data/preprocessing.py::encode_event`:

| Offset | Dims | Content |
|---|---|---|
| 0-4 | 5 | Event-type one-hot (`user_message`, `llm_response`, `tool_call`, `tool_result`, `agent_response`) |
| 5-20 | 16 | Tool one-hot: 6 known + 10 hash-bucketed unknowns |
| 21 | 1 | Latency / 60 s |
| 22 | 1 | `tokens_in` / 4096 |
| 23 | 1 | `tokens_out` / 4096 |
| 24 | 1 | `user_initiated` (binary) |
| 25 | 1 | Time delta from previous event / 120 s |
| 26 | 1 | External source flag (not `internal`/`unknown`/`""`) |
| 27 | 1 | `has_tool_calls` flag |

All features are in `[0, 1]` by construction. Unknown tool names hash into
slots 5+len(KNOWN_TOOLS)..5+NUM_TOOL_SLOTS-1 (10 slots) rather than a single
bucket — this lets the model distinguish families of unknown tools rather
than collapsing all novel tools into one class.

---

## 4. Fusion

File: [`models/fusion.py`](../models/fusion.py). Factory:
`build_fusion(strategy, d_model, n_heads, latent_dim)`.

### 4.1 `cross_attention` (default, best in sweep)

Consumes **full encoder sequences** (not pooled vectors):

```
z1_seq [B, T1, d_model]    (Stream 1 post-Mamba)
z2_seq [B, T2, d_model]    (Stream 2 post-Transformer)
z2_mask [B, T2]            (1=real, 0=pad)

# Direction 1: z1 attends to z2
fused_1to2, attn_1to2 = MultiheadAttention(z1, z2, z2, key_padding_mask=kpm_z2)
z1_out = LayerNorm(z1_seq + fused_1to2)

# Direction 2: z2 attends to z1
fused_2to1, attn_2to1 = MultiheadAttention(z2, z1, z1, key_padding_mask=kpm_z1)
z2_out = LayerNorm(z2_seq + fused_2to1)

# Masked mean pool each fused sequence over time
z1_pool = masked_mean(z1_out, z1_mask)  # [B, d_model]
z2_pool = masked_mean(z2_out, z2_mask)  # [B, d_model]

# Project to latent
latent = MLP(concat[z1_pool, z2_pool])  # [B, latent_dim]
```

**Why bidirectional?** Unidirectional `z1 ← z2` would let telemetry attend to
actions, but not the reverse — so the Transformer side could never consult
"was there a simultaneous CPU spike?" when ranking event suspicion. Both
directions together let each modality ask questions of the other.

**Per-head attention export.** `_last_attn_weights` is populated on every
forward pass (detached), and `return_attention=True` returns the live
tensors. `scripts/plots/run_all.py` aggregates these per attack category.

### 4.2 Weaker variants (ablation / sweep only)

| Strategy | Input | Description |
|---|---|---|
| `concat_mlp` | pooled `[B, d_model]` each | Concat → 2-layer MLP. Simplest. |
| `gated` | pooled | `g = σ(W·[z1;z2])`; `fused = g·z1 + (1-g)·z2`. Lossy but parameter-lean. |
| `attention_pool` | pooled | Stack as 2-token sequence → self-attention → mean pool → linear. |

### 4.3 Numerical safety

`_safe_key_padding_mask` unmasks key 0 when a sample has all padding.
Otherwise, `MultiheadAttention` softmaxes over a fully-masked key set and
emits NaN, which propagates through the reconstruction loss and kills the
trainer. This failure mode is not theoretical — it fires on benign windows
with zero action events in Stream 2.

---

## 5. Reconstruction decoders

From [`models/agentguard.py`](../models/agentguard.py):

```python
self.stream1_decoder = Sequential(Linear(latent, latent), act, Linear(latent, 32))
self.stream2_decoder = Sequential(Linear(latent, 256), act, Linear(256, 64*28))
```

The Stream 2 decoder reconstructs the **entire** `[64, 28]` sequence from
the pooled latent — intentional asymmetry, because forcing the latent to
"remember" every position makes it more information-dense than decoding only
the last event. Masked MSE (see `ReconstructionLoss` in `training/losses.py`)
only penalises the real (non-pad) positions.

---

## 6. Anomaly classification head

```python
def _build_cls_head(latent_dim, n_layers, hidden_dim, act_cls):
    if n_layers == 1: return Sequential(Linear(latent, 1), Sigmoid())
    if n_layers == 2: return Sequential(Linear(latent, hidden), act, Linear(hidden, 1), Sigmoid())
    if n_layers == 3: return Sequential(Linear(latent, hidden), act,
                                         Linear(hidden, hidden//2), act,
                                         Linear(hidden//2, 1), Sigmoid())
```

The best config uses `cls_head_layers=1` — a single Linear + Sigmoid —
because Phase 1 of the sweep showed deeper heads actively hurt. Intuition:
the post-fusion latent is already well-shaped by SupCon, so the head only
needs to read off a direction.

---

## 7. Forward passes (two paths)

```python
if self.use_sequence_fusion:                # cross_attention only
    z1_seq = Stream1Encoder(stream1, return_sequence=True)
    z2_seq = Stream2Encoder(stream2_seq, stream2_mask, return_sequence=True)
    latent = Fusion(z1_seq, z2_seq, z1_mask=None, z2_mask=stream2_mask)
else:                                       # concat_mlp / gated / attention_pool
    z1 = Stream1Encoder(stream1)            # [B, d_model] (last timestep)
    z2 = Stream2Encoder(stream2_seq, stream2_mask)   # [B, d_model] (masked mean)
    latent = Fusion(z1, z2)
```

This branch is one of the few places in the code where `fusion_strategy`
has a structural effect beyond module selection.

---

## 8. Parameter counts (best config, default sweep)

| Component | Params |
|---|---|
| Stream1Encoder (4 × MambaBlock @ d_model=128) | ~830 k |
| Stream2Encoder (1-layer Transformer, d_model=128, ff=1024, heads=8) | ~265 k |
| CrossAttentionFusion (2 × MHA + 2×2d_model MLP) | ~330 k |
| Reconstruction decoders + anomaly head | ~520 k |
| **Total** | **~1.95 M** |

For reference, the sweep's architecture range spanned `d_model ∈ {64, 128,
256, 512}` and `latent_dim ∈ {64, 128, 256}`; the 512 configurations
dominate memory but do not improve AUROC and sometimes trigger OOM on mid-
range GPUs (handled by the sweep with `trial → 0.0` return on OOM).

---

## 9. See also

- [`training.md`](./training.md) — trainer loop, loss weights, CV protocol.
- [`evaluation.md`](./evaluation.md) — metrics, interpretability pipeline,
  attention visualisations.
- [`models/fusion.py`](../models/fusion.py) — all four fusion variants in one
  file with docstrings.
