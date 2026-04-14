"""
Phase B smoke test — sequence-level cross-attention fusion with weight extraction.

Exercises AgentGuardModel with fusion_strategy="cross_attention" end-to-end:
  * Non-degenerate per-head attention weights of the correct shape
  * Masked sequence positions receive ~0 attention
  * Output dict shape unchanged when return_attention is not requested
  * Non-cross-attention (gated) path still runs unchanged

Run from repo root:
    python -m tests.phase_b_smoke
"""

import sys
from pathlib import Path

# Allow running as a script: add repo root to sys.path if needed.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import torch

from models.agentguard import AgentGuardModel


def _build_model(fusion_strategy: str) -> AgentGuardModel:
    return AgentGuardModel(
        stream1_input_dim=32,
        stream2_input_dim=28,
        d_model=128,
        latent_dim=128,
        transformer_heads=8,
        max_seq_len=64,
        fusion_strategy=fusion_strategy,
    )


def _cross_attention_smoke() -> None:
    print("=" * 72)
    print("Cross-attention fusion smoke test")
    print("=" * 72)

    torch.manual_seed(0)
    model = _build_model("cross_attention").eval()

    B = 4
    stream1 = torch.randn(B, 8, 32)
    stream2_seq = torch.randn(B, 64, 28)
    stream2_mask = torch.ones(B, 64)
    # Mask last 20 positions of the first sample — they should get ~0 attention.
    stream2_mask[0, 44:] = 0.0

    with torch.no_grad():
        outputs = model(stream1, stream2_seq, stream2_mask, return_attention=True)

    expected_keys = {"latent", "stream1_recon", "stream2_recon", "anomaly_score",
                     "attention_weights"}
    assert expected_keys.issubset(outputs.keys()), (
        f"Missing keys; got {sorted(outputs.keys())}, expected {sorted(expected_keys)}"
    )
    print(f"Output keys: {sorted(outputs.keys())}")

    attn = outputs["attention_weights"]
    attn_1to2 = attn["1to2"]
    attn_2to1 = attn["2to1"]
    print(f"attn['1to2'].shape = {tuple(attn_1to2.shape)}")
    print(f"attn['2to1'].shape = {tuple(attn_2to1.shape)}")
    assert attn_1to2.shape == (B, 8, 8, 64), (
        f"1to2 shape mismatch: {tuple(attn_1to2.shape)}"
    )
    assert attn_2to1.shape == (B, 8, 64, 8), (
        f"2to1 shape mismatch: {tuple(attn_2to1.shape)}"
    )

    std_1to2 = attn_1to2.std().item()
    print(f"attn['1to2'].std() = {std_1to2:.6f}")
    assert std_1to2 > 1e-4, f"attention weights degenerate: std={std_1to2}"

    # Masked sample: positions 44.. should receive near-zero attention in 1to2.
    masked_region = attn_1to2[0, :, :, 44:].abs().mean().item()
    print(f"masked-region |attn| mean (sample 0, keys 44:) = {masked_region:.3e}")
    assert masked_region < 1e-4, (
        f"masked keys received non-trivial attention: {masked_region}"
    )

    # Latent and reconstruction shapes unchanged.
    assert outputs["latent"].shape == (B, 128), outputs["latent"].shape
    assert outputs["stream1_recon"].shape == (B, 32), outputs["stream1_recon"].shape
    assert outputs["stream2_recon"].shape == (B, 64, 28), outputs["stream2_recon"].shape
    assert outputs["anomaly_score"].shape == (B, 1), outputs["anomaly_score"].shape
    print(f"latent.shape = {tuple(outputs['latent'].shape)}")
    print(f"stream1_recon.shape = {tuple(outputs['stream1_recon'].shape)}")
    print(f"stream2_recon.shape = {tuple(outputs['stream2_recon'].shape)}")
    print(f"anomaly_score.shape = {tuple(outputs['anomaly_score'].shape)}")

    # --- Second call: without return_attention — attention_weights must be absent.
    with torch.no_grad():
        plain_outputs = model(stream1, stream2_seq, stream2_mask)
    assert "attention_weights" not in plain_outputs, (
        "attention_weights must be absent when return_attention=False; "
        f"got keys {sorted(plain_outputs.keys())}"
    )
    for k in ("latent", "stream1_recon", "stream2_recon", "anomaly_score"):
        assert plain_outputs[k].shape == outputs[k].shape, (
            f"shape drift on {k}: {plain_outputs[k].shape} vs {outputs[k].shape}"
        )
    print("plain-call keys:", sorted(plain_outputs.keys()))

    # Fusion module still cached detached weights even without return_attention.
    cached = model.fusion._last_attn_weights
    assert cached is not None, "fusion._last_attn_weights not populated"
    assert not cached["1to2"].requires_grad, "cached weights are not detached"
    print("cached _last_attn_weights: 1to2.shape =",
          tuple(cached["1to2"].shape), "requires_grad=", cached["1to2"].requires_grad)

    print("Cross-attention smoke: OK")


def _gated_fusion_smoke() -> None:
    print("=" * 72)
    print("Gated fusion (non-sequence path) smoke test")
    print("=" * 72)

    torch.manual_seed(0)
    model = _build_model("gated").eval()

    B = 4
    stream1 = torch.randn(B, 8, 32)
    stream2_seq = torch.randn(B, 64, 28)
    stream2_mask = torch.ones(B, 64)

    with torch.no_grad():
        outputs = model(stream1, stream2_seq, stream2_mask)

    # Non-cross-attention: attention_weights must NOT appear.
    assert "attention_weights" not in outputs, (
        f"unexpected attention_weights in non-cross-attention path: "
        f"{sorted(outputs.keys())}"
    )
    assert outputs["latent"].shape == (B, 128)
    assert outputs["stream1_recon"].shape == (B, 32)
    assert outputs["stream2_recon"].shape == (B, 64, 28)
    assert outputs["anomaly_score"].shape == (B, 1)
    print("gated path keys:", sorted(outputs.keys()))

    # Asking for return_attention on a non-cross-attention model should still work
    # (it simply won't include the key).
    with torch.no_grad():
        outputs2 = model(stream1, stream2_seq, stream2_mask, return_attention=True)
    assert "attention_weights" not in outputs2, (
        "non-cross-attention model must not emit attention_weights"
    )
    print("gated path + return_attention=True keys:", sorted(outputs2.keys()))

    print("Gated-fusion smoke: OK")


def main() -> int:
    _cross_attention_smoke()
    _gated_fusion_smoke()
    print("=" * 72)
    print("ALL PHASE B SMOKE TESTS PASSED")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
