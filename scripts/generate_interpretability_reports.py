#!/usr/bin/env python3
"""Generate per-sample interpretability reports for AgentGuard.

Loads a trained checkpoint, runs inference on the test fold, then for each
attack category picks the top-N highest-scoring true positives (plus up to N
highest-score false positives and lowest-score false negatives across the
whole fold) and produces a markdown detection report + attribution heatmap
PNG for each.

Usage:
    python scripts/generate_interpretability_reports.py \
        --config config_best.yml --seed 42 --fold 1 \
        --out_dir results/reports --n_per_category 3
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader

# Ensure project root is on the path when running from anywhere.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from main import build_model, build_loaders_from_splits, load_config, make_stratified_folds  # noqa: E402
from data.dataset.collate import agentguard_collate  # noqa: E402
from data.dataset.telemetry_dataset import AgentGuardDataset  # noqa: E402

from agentguard.interpretability import (  # noqa: E402
    attribute_temporal,
    flag_action_pairs,
    compute_benign_baseline,
    feature_zscores,
    render_report,
)


_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


def slugify(name: str) -> str:
    """Lowercase alnum+underscore slug, safe as a directory name."""
    if not name:
        return "unknown"
    slug = _SLUG_RE.sub("_", name).strip("_").lower()
    return slug or "unknown"


def derive_fold_agents(config: Dict, fold: int) -> Tuple[List[str], List[str], List[str]]:
    """Reproduce the fold split used during CV training.

    Returns (train_agents, val_agents, test_agents) for ``fold`` (1-indexed).
    """
    data_cfg = config["data"]
    attacked = data_cfg["attacked_agents"]
    control = data_cfg["control_agents"]
    k = data_cfg["k_folds"]
    folds = make_stratified_folds(attacked, control, k)

    fold_idx = fold - 1
    if not (0 <= fold_idx < k):
        raise ValueError(f"fold must be in [1, {k}], got {fold}")

    test_agents = folds[fold_idx]
    val_agents = folds[(fold_idx + 1) % k]
    train_agents: List[str] = []
    for j in range(k):
        if j != fold_idx and j != (fold_idx + 1) % k:
            train_agents.extend(folds[j])
    return train_agents, val_agents, test_agents


def build_benign_baselines(config: Dict, train_agents: List[str]) -> Dict[str, Dict[str, np.ndarray]]:
    """Compute per-agent benign baselines from the TRAIN fold only.

    Uses the raw (un-normalized) stream1 tensors from each agent's .pt file,
    filtered to label==0 windows. Falls back to zero-mean/unit-std when an
    agent has no benign windows.
    """
    processed_dir = Path(config["data"]["processed_dir"])
    baselines: Dict[str, Dict[str, np.ndarray]] = {}
    for agent_id in train_agents:
        pt_path = processed_dir / f"{agent_id}.pt"
        if not pt_path.exists():
            print(f"[baseline] {agent_id}: .pt missing, skipping")
            continue
        data = torch.load(pt_path, map_location="cpu", weights_only=True)
        stream1 = data["stream1"].numpy()   # [N, 32] raw
        labels = data["labels"].numpy()     # [N]
        benign = stream1[labels == 0]
        baselines[agent_id] = compute_benign_baseline(agent_id, benign)
        print(
            f"[baseline] {agent_id}: {benign.shape[0]} benign windows "
            f"(total {stream1.shape[0]})"
        )
    return baselines


def _fallback_baseline() -> Dict[str, np.ndarray]:
    return {
        "mean": np.zeros(32, dtype=np.float64),
        "std": np.ones(32, dtype=np.float64),
    }


def _ensure_checkpoint(checkpoint_path: Path, config: Dict) -> Tuple[bool, Path]:
    """Ensure a checkpoint exists at ``checkpoint_path``.

    If missing, save a random-initialized model to that path so the driver
    can still run end-to-end. Returns (used_stub, checkpoint_path).
    """
    if checkpoint_path.exists():
        return False, checkpoint_path
    print(
        f"[warning] Checkpoint missing at {checkpoint_path}; saving a "
        f"random-initialized model as a stub so the driver can run."
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    model = build_model(config)
    torch.save({"model_state_dict": model.state_dict()}, checkpoint_path)
    return True, checkpoint_path


def load_checkpoint_into(model: torch.nn.Module, checkpoint_path: Path, device: str) -> None:
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    if isinstance(ckpt, dict) and "model_state_dict" in ckpt:
        model.load_state_dict(ckpt["model_state_dict"])
    else:
        model.load_state_dict(ckpt)


def get_raw_stream1(test_ds: AgentGuardDataset, agent_idx: int,
                    window_idx: int) -> np.ndarray:
    """Return the raw (un-normalized) [32] stream1 vector for the sample's
    last-window slot, used for z-score deviations against the benign baseline.
    """
    return test_ds.agent_data[agent_idx]["stream1"][window_idx].numpy().astype(np.float64)


def run_inference(model: torch.nn.Module, test_loader: DataLoader, device: str
                  ) -> List[Dict]:
    """Run inference over the test loader and return one record per sample."""
    model.eval()
    records: List[Dict] = []
    with torch.no_grad():
        for batch in test_loader:
            stream1 = batch["stream1"].to(device)
            stream2_seq = batch["stream2_seq"].to(device)
            stream2_mask = batch["stream2_mask"].to(device)
            out = model(stream1, stream2_seq, stream2_mask)
            scores = out["anomaly_score"].squeeze(-1).cpu().numpy()
            labels = batch["label"].cpu().numpy()
            for i in range(len(scores)):
                records.append({
                    "agent_id": batch["agent_id"][i],
                    "agent_idx": int(batch["agent_idx"][i].item()),
                    "window_idx": int(batch["window_idx"][i].item()),
                    "attack_id": batch["attack_id"][i],
                    "attack_category": batch["attack_category"][i],
                    "y_true": int(labels[i]),
                    "y_score": float(scores[i]),
                })
    return records


def pick_per_category(records: List[Dict], n: int) -> Dict[str, List[Dict]]:
    """For each non-empty attack_category (label==1), take top-n by score."""
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for r in records:
        if r["y_true"] == 1 and r["attack_category"]:
            buckets[r["attack_category"]].append(r)
    selected: Dict[str, List[Dict]] = {}
    for cat, rows in buckets.items():
        rows.sort(key=lambda x: x["y_score"], reverse=True)
        selected[cat] = rows[:n]
    return selected


def pick_errors(records: List[Dict], n: int, threshold: float = 0.5
                ) -> Tuple[List[Dict], List[Dict]]:
    """Pick highest-score false positives and lowest-score false negatives."""
    fp = [r for r in records if r["y_true"] == 0 and r["y_score"] >= threshold]
    fn = [r for r in records if r["y_true"] == 1 and r["y_score"] < threshold]
    fp.sort(key=lambda r: r["y_score"], reverse=True)
    fn.sort(key=lambda r: r["y_score"])
    return fp[:n], fn[:n]


def _find_sample_in_dataset(test_ds: AgentGuardDataset, agent_idx: int,
                            window_idx: int) -> int:
    """Linear scan to find the dataset index for a given (agent_idx, window_idx)."""
    for ds_idx, (a, w) in enumerate(test_ds.samples):
        if a == agent_idx and w == window_idx:
            return ds_idx
    raise KeyError(
        f"Could not locate sample agent_idx={agent_idx} window_idx={window_idx}"
    )


def generate_one_report(
    record: Dict,
    test_ds: AgentGuardDataset,
    model: torch.nn.Module,
    baselines: Dict[str, Dict[str, np.ndarray]],
    device: str,
    out_dir: Path,
    top_k_features: int = 5,
    top_k_pairs: int = 5,
    ig_steps: int = 50,
) -> Path:
    """Produce the markdown + PNG for one record. Returns the md path."""
    ds_idx = _find_sample_in_dataset(test_ds, record["agent_idx"], record["window_idx"])
    sample = test_ds[ds_idx]

    stream1 = sample["stream1"].unsqueeze(0).to(device)
    stream2_seq = sample["stream2_seq"].unsqueeze(0).to(device)
    stream2_mask = sample["stream2_mask"].unsqueeze(0).to(device)

    temporal_attr = attribute_temporal(
        model, stream1, stream2_seq, stream2_mask, n_steps=ig_steps,
    )
    pairs = flag_action_pairs(
        model, stream1, stream2_seq, stream2_mask, top_k=top_k_pairs,
    )

    raw_s1 = get_raw_stream1(test_ds, record["agent_idx"], record["window_idx"])
    baseline = baselines.get(record["agent_id"], _fallback_baseline())
    zresult = feature_zscores(raw_s1, baseline)
    zresult_top = {
        "zscores": zresult["zscores"],
        "top_k": zresult["top_k"][:top_k_features],
    }

    meta = {
        "agent_id": record["agent_id"],
        "window_idx": record["window_idx"],
        "attack_id": record["attack_id"],
        "attack_category": record["attack_category"],
        "y_true": record["y_true"],
        "y_score": record["y_score"],
    }

    md = render_report(
        sample_meta=meta,
        temporal_attr=temporal_attr,
        action_pairs=pairs,
        feature_zscores=zresult_top,
        figure_dir=out_dir,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{record['agent_id']}_{record['window_idx']}.md"
    md_path.write_text(md, encoding="utf-8")
    return md_path


def write_index(out_root: Path, written: Dict[str, List[Path]]) -> Path:
    """Write the top-level index.md linking to every generated report."""
    lines: List[str] = []
    lines.append("# AgentGuard interpretability reports")
    lines.append("")
    for section in sorted(written.keys()):
        lines.append(f"## {section}")
        lines.append("")
        for p in sorted(written[section]):
            rel = p.relative_to(out_root).as_posix()
            lines.append(f"- [{rel}](./{rel})")
        lines.append("")
    index_path = out_root / "index.md"
    out_root.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate AgentGuard per-sample interpretability reports."
    )
    parser.add_argument("--config", default="config_best.yml")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fold", type=int, default=1)
    parser.add_argument("--out_dir", default="results/reports")
    parser.add_argument("--n_per_category", type=int, default=3)
    parser.add_argument("--ig_steps", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    config = load_config(args.config)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    # Seed
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    # Build fold splits that match training-time CV.
    train_agents, val_agents, test_agents = derive_fold_agents(config, args.fold)
    print(f"Fold {args.fold}: train={train_agents}")
    print(f"Fold {args.fold}: val  ={val_agents}")
    print(f"Fold {args.fold}: test ={test_agents}")

    # Build loaders via the canonical path so normalization matches training.
    # We only need the test loader; build_loaders_from_splits also constructs
    # train & val datasets to compute shared normalization stats.
    train_loader, val_loader, test_loader = build_loaders_from_splits(
        config, train_agents, val_agents, test_agents,
    )
    test_ds: AgentGuardDataset = test_loader.dataset

    # Ensure checkpoint exists (fall back to stub) and instantiate the model.
    processed_dir = Path(config["data"]["processed_dir"])
    checkpoint_path = processed_dir / "checkpoints" / f"model_seed{args.seed}_fold{args.fold}.pt"
    used_stub, checkpoint_path = _ensure_checkpoint(checkpoint_path, config)

    model = build_model(config)
    load_checkpoint_into(model, checkpoint_path, device)
    model.to(device)
    model.eval()

    # Per-agent benign baselines from the TRAIN fold.
    baselines = build_benign_baselines(config, train_agents)

    # Run inference across the test set.
    print("Running inference on the test fold...")
    records = run_inference(model, test_loader, device)
    print(f"  {len(records)} samples scored.")

    # Bucket by category and pick representatives.
    per_category = pick_per_category(records, args.n_per_category)
    fp, fn = pick_errors(records, args.n_per_category)

    if used_stub:
        # For random-init stubs, make sure we still produce at least one report
        # per attack category present in the test fold. Fall back to the
        # top-score sample regardless of y_true if none were selected.
        observed_cats = {r["attack_category"] for r in records
                         if r["y_true"] == 1 and r["attack_category"]}
        for cat in observed_cats:
            if cat not in per_category or not per_category[cat]:
                cands = [r for r in records
                         if r["attack_category"] == cat and r["y_true"] == 1]
                cands.sort(key=lambda r: r["y_score"], reverse=True)
                per_category[cat] = cands[: args.n_per_category]

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    written: Dict[str, List[Path]] = defaultdict(list)

    # Category reports.
    for category, rows in per_category.items():
        slug = slugify(category)
        sub_dir = out_root / slug
        for rec in rows:
            try:
                md_path = generate_one_report(
                    rec, test_ds, model, baselines, device, sub_dir,
                    ig_steps=args.ig_steps,
                )
                written[category].append(md_path)
                print(f"  [{category}] -> {md_path}")
            except Exception as e:  # noqa: BLE001
                print(f"  [{category}] FAILED for {rec}: {e}")

    # Error-type reports.
    fp_dir = out_root / "false_positives"
    for rec in fp:
        try:
            md_path = generate_one_report(
                rec, test_ds, model, baselines, device, fp_dir,
                ig_steps=args.ig_steps,
            )
            written["false_positives"].append(md_path)
            print(f"  [false_positives] -> {md_path}")
        except Exception as e:  # noqa: BLE001
            print(f"  [false_positives] FAILED for {rec}: {e}")

    fn_dir = out_root / "false_negatives"
    for rec in fn:
        try:
            md_path = generate_one_report(
                rec, test_ds, model, baselines, device, fn_dir,
                ig_steps=args.ig_steps,
            )
            written["false_negatives"].append(md_path)
            print(f"  [false_negatives] -> {md_path}")
        except Exception as e:  # noqa: BLE001
            print(f"  [false_negatives] FAILED for {rec}: {e}")

    index_path = write_index(out_root, written)
    total = sum(len(v) for v in written.values())
    print(f"\nWrote {total} reports across {len(written)} sections.")
    print(f"Index: {index_path}")
    if used_stub:
        print(
            "[note] A random-initialized stub checkpoint was used; scores and "
            "attributions are not meaningful until a real fold checkpoint exists."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
