"""Smoke test: load AgentGuard checkpoint, run one forward pass on random tensors.
Exits non-zero on failure. Run inside the control_plane image.
"""
import os
import sys
import yaml
import torch

sys.path.insert(0, "/workspace")
from models.agentguard import AgentGuardModel


def main() -> int:
    cfg_path = os.environ.get("AGENTGUARD_CONFIG", "/workspace/config.yml")
    ckpt_path = os.environ.get(
        "AGENTGUARD_CHECKPOINT",
        "/workspace/data/processed/checkpoints/best_model.pt",
    )

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    m = cfg["model"]

    model = AgentGuardModel(
        stream1_input_dim=m["stream1_input_dim"],
        stream2_input_dim=m["stream2_input_dim"],
        d_model=m["d_model"],
        latent_dim=m["latent_dim"],
        mamba_layers=m["mamba_layers"],
        transformer_layers=m["transformer_layers"],
        transformer_heads=m["transformer_heads"],
        transformer_ff_dim=m["transformer_ff_dim"],
        dropout=m["dropout"],
        max_seq_len=cfg["data"]["max_seq_len"],
        fusion_strategy=m["fusion_strategy"],
        cls_head_layers=m["cls_head_layers"],
        cls_head_hidden_dim=m["cls_head_hidden_dim"],
        cls_head_activation=m["cls_head_activation"],
        decoder_activation=m["decoder_activation"],
    )
    state = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if isinstance(state, dict) and "model_state_dict" in state:
        state = state["model_state_dict"]
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        print(f"WARN: missing={missing} unexpected={unexpected}", file=sys.stderr)
    model.eval()

    seq_ctx = cfg["data"]["seq_context"]
    max_len = cfg["data"]["max_seq_len"]
    s1 = torch.randn(1, seq_ctx, m["stream1_input_dim"])
    s2 = torch.randn(1, max_len, m["stream2_input_dim"])
    mask = torch.ones(1, max_len, dtype=torch.bool)

    with torch.no_grad():
        out = model(s1, s2, mask)

    score = out["anomaly_score"].item()
    assert 0.0 <= score <= 1.0, f"score out of range: {score}"
    print(f"smoke OK; anomaly_score={score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
