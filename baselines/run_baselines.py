from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import csv

import numpy as np
import torch
import yaml
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from baselines.dataset import FlatTensorDataset, SeqTensorDataset
from baselines.features import build_fold_tensors
from baselines.models.cnn_ae import CNNAE
from baselines.models.deep_svdd import DeepSVDDNet, score_deep_svdd, train_deep_svdd
from baselines.models.lstm_ae import LSTMAE
from baselines.models.transformer_ae import TransformerAE
from baselines.train_torch import score_ae, train_ae
from main import make_stratified_folds, set_global_seed


# Map human-readable baseline names used in rows/markdown to the lowercase
# filename-safe slugs used for the predictions/*.npz dumps.
BASELINE_SLUGS = {
    "IsolationForest": "isolation_forest",
    "LSTMAE": "lstm_ae",
    "CNNAE": "cnn_ae",
    "TransformerAE": "transformer_ae",
    "DeepSVDD": "deep_svdd",
}


def pick_threshold(scores_val: np.ndarray, labels_val: np.ndarray) -> float:
    thrs = np.quantile(scores_val, np.linspace(0, 1, 101))
    best_f1, best_t = -1.0, 0.5
    for t in thrs:
        preds = (scores_val >= t).astype(int)
        f1 = f1_score(labels_val, preds, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_t = float(t)
    return best_t


def compute_metrics(scores_val, labels_val, scores_test, labels_test):
    """Return (auroc, auprc, f1, threshold). If the test fold has only one
    class, return 0.0 for auroc/auprc/f1 and 0.5 for threshold (matches
    trainer.py's convention for degenerate folds)."""
    import numpy as np
    labels_val  = np.asarray(labels_val).astype(int)
    labels_test = np.asarray(labels_test).astype(int)
    if len(np.unique(labels_test)) < 2 or len(np.unique(labels_val)) < 2:
        return 0.0, 0.0, 0.0, 0.5
    auroc = float(roc_auc_score(labels_test, scores_test))
    auprc = float(average_precision_score(labels_test, scores_test))
    thr = pick_threshold(scores_val, labels_val)
    f1  = float(f1_score(labels_test, (scores_test >= thr).astype(int), zero_division=0))
    return auroc, auprc, f1, thr


def _save_predictions(
    pred_dir: Path,
    baseline: str,
    seed: int,
    fold: int,
    y_true: np.ndarray,
    y_score: np.ndarray,
) -> None:
    """Persist raw (y_true, y_score) for a single (baseline, seed, fold).

    When a fold is skipped because of an empty normal-only split, this is still
    called with empty arrays so the downstream loader can detect and ignore
    the file while preserving the full (baseline, seed, fold) grid on disk.
    """
    slug = BASELINE_SLUGS[baseline]
    pred_dir.mkdir(parents=True, exist_ok=True)
    out_path = pred_dir / f"{slug}_seed{seed}_fold{fold}.npz"
    np.savez(
        out_path,
        y_true=np.asarray(y_true, dtype=np.int64),
        y_score=np.asarray(y_score, dtype=np.float64),
    )


def run(args: argparse.Namespace) -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    with open(args.config, "r") as fh:
        config = yaml.safe_load(fh)

    data_cfg = config["data"]
    attacked: list[str] = data_cfg["attacked_agents"]
    control: list[str] = data_cfg["control_agents"]
    processed_dir: str = data_cfg["processed_dir"]
    seq_context: int = int(data_cfg.get("seq_context", 8))
    k_folds: int = int(data_cfg["k_folds"])

    epochs = 3 if args.fast else 50
    patience = 5
    batch_size = 64
    lr = 1e-3

    pred_dir = Path("predictions")

    rows: list[dict] = []

    for seed in args.seeds:
        set_global_seed(seed)
        print(f"\n=== seed={seed} ===")

        folds = make_stratified_folds(attacked, control, k=k_folds)

        for i in range(k_folds):
            fold_idx = i + 1
            test_ids = folds[i]
            val_ids = folds[(i + 1) % k_folds]
            train_ids = [
                a
                for j, f in enumerate(folds)
                if j not in (i, (i + 1) % k_folds)
                for a in f
            ]

            test_set = set(test_ids)
            val_set = set(val_ids)
            train_set = set(train_ids)
            assert not test_set & val_set, "test/val overlap"
            assert not test_set & train_set, "test/train overlap"
            assert not val_set & train_set, "val/train overlap"

            print(f"\n[seed {seed} | fold {fold_idx}/{k_folds}] building tensors ...")
            tensors = build_fold_tensors(
                processed_dir, train_ids, val_ids, test_ids, seq_context=seq_context
            )

            train_mask = tensors["train"]["labels"] == 0
            seq_train_norm = tensors["train"]["seq"][train_mask]
            flat_train_norm = tensors["train"]["flat"][train_mask]
            lbl_train_norm = torch.zeros(seq_train_norm.shape[0], dtype=torch.long)

            val_mask = tensors["val"]["labels"] == 0
            seq_val_norm = tensors["val"]["seq"][val_mask]
            flat_val_norm = tensors["val"]["flat"][val_mask]
            lbl_val_norm = torch.zeros(seq_val_norm.shape[0], dtype=torch.long)

            def _seq_loader(seq, lbl, shuffle: bool) -> DataLoader:
                return DataLoader(
                    SeqTensorDataset(seq, lbl),
                    batch_size=batch_size,
                    shuffle=shuffle,
                )

            def _flat_loader(flat, lbl, shuffle: bool) -> DataLoader:
                return DataLoader(
                    FlatTensorDataset(flat, lbl),
                    batch_size=batch_size,
                    shuffle=shuffle,
                )

            def _full_seq_loader(split: str) -> DataLoader:
                return _seq_loader(
                    tensors[split]["seq"], tensors[split]["labels"], shuffle=False
                )

            def _full_flat_loader(split: str) -> DataLoader:
                return _flat_loader(
                    tensors[split]["flat"], tensors[split]["labels"], shuffle=False
                )

            # ------------------------------------------------------------------
            # Isolation Forest
            # ------------------------------------------------------------------
            train_flat_np = tensors["train"]["flat"].numpy()
            train_anomaly_rate = float(tensors["train"]["labels"].float().mean().item())
            cont = min(max(train_anomaly_rate, 1e-4), 0.5)
            clf = IsolationForest(
                n_estimators=200, contamination=cont, random_state=seed, n_jobs=-1
            )
            clf.fit(train_flat_np)
            scores_val_if = -clf.decision_function(tensors["val"]["flat"].numpy())
            scores_test_if = -clf.decision_function(tensors["test"]["flat"].numpy())
            labels_val_if = tensors["val"]["labels"].numpy()
            labels_test_if = tensors["test"]["labels"].numpy()

            auroc, auprc, f1, thr_if = compute_metrics(scores_val_if, labels_val_if, scores_test_if, labels_test_if)
            print(
                f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=IsolationForest "
                f"AUROC={auroc:.4f} AUPRC={auprc:.4f} F1={f1:.4f}"
            )
            rows.append(
                dict(baseline="IsolationForest", seed=seed, fold=fold_idx,
                     auroc=auroc, auprc=auprc, f1=f1, threshold=thr_if)
            )
            _save_predictions(
                pred_dir, "IsolationForest", seed, fold_idx,
                labels_test_if, scores_test_if,
            )

            # ------------------------------------------------------------------
            # LSTM-AE
            # ------------------------------------------------------------------
            if seq_train_norm.shape[0] == 0 or seq_val_norm.shape[0] == 0:
                print(f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=LSTMAE skipped (empty normal-only split)")
                rows.append({"baseline": "LSTMAE", "seed": seed, "fold": fold_idx,
                             "auroc": 0.0, "auprc": 0.0, "f1": 0.0, "threshold": 0.5})
                _save_predictions(
                    pred_dir, "LSTMAE", seed, fold_idx,
                    np.array([]), np.array([]),
                )
            else:
                lstm_ae = LSTMAE()
                train_ae(
                    lstm_ae,
                    _seq_loader(seq_train_norm, lbl_train_norm, shuffle=True),
                    _seq_loader(seq_val_norm, lbl_val_norm, shuffle=False),
                    device=device,
                    epochs=epochs,
                    lr=lr,
                    weight_decay=1e-5,
                    patience=patience,
                    verbose=False,
                )
                scores_val_lstm, labels_val_lstm = score_ae(lstm_ae, _full_seq_loader("val"), device=device)
                scores_test_lstm, labels_test_lstm = score_ae(lstm_ae, _full_seq_loader("test"), device=device)
                auroc, auprc, f1, thr_lstm = compute_metrics(scores_val_lstm, labels_val_lstm, scores_test_lstm, labels_test_lstm)
                print(
                    f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=LSTMAE "
                    f"AUROC={auroc:.4f} AUPRC={auprc:.4f} F1={f1:.4f}"
                )
                rows.append(
                    dict(baseline="LSTMAE", seed=seed, fold=fold_idx,
                         auroc=auroc, auprc=auprc, f1=f1, threshold=thr_lstm)
                )
                _save_predictions(
                    pred_dir, "LSTMAE", seed, fold_idx,
                    labels_test_lstm, scores_test_lstm,
                )

            # ------------------------------------------------------------------
            # CNN-AE
            # ------------------------------------------------------------------
            if seq_train_norm.shape[0] == 0 or seq_val_norm.shape[0] == 0:
                print(f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=CNNAE skipped (empty normal-only split)")
                rows.append({"baseline": "CNNAE", "seed": seed, "fold": fold_idx,
                             "auroc": 0.0, "auprc": 0.0, "f1": 0.0, "threshold": 0.5})
                _save_predictions(
                    pred_dir, "CNNAE", seed, fold_idx,
                    np.array([]), np.array([]),
                )
            else:
                cnn_ae = CNNAE()
                train_ae(
                    cnn_ae,
                    _seq_loader(seq_train_norm, lbl_train_norm, shuffle=True),
                    _seq_loader(seq_val_norm, lbl_val_norm, shuffle=False),
                    device=device,
                    epochs=epochs,
                    lr=lr,
                    weight_decay=1e-5,
                    patience=patience,
                    verbose=False,
                )
                scores_val_cnn, labels_val_cnn = score_ae(cnn_ae, _full_seq_loader("val"), device=device)
                scores_test_cnn, labels_test_cnn = score_ae(cnn_ae, _full_seq_loader("test"), device=device)
                auroc, auprc, f1, thr_cnn = compute_metrics(scores_val_cnn, labels_val_cnn, scores_test_cnn, labels_test_cnn)
                print(
                    f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=CNNAE "
                    f"AUROC={auroc:.4f} AUPRC={auprc:.4f} F1={f1:.4f}"
                )
                rows.append(
                    dict(baseline="CNNAE", seed=seed, fold=fold_idx,
                         auroc=auroc, auprc=auprc, f1=f1, threshold=thr_cnn)
                )
                _save_predictions(
                    pred_dir, "CNNAE", seed, fold_idx,
                    labels_test_cnn, scores_test_cnn,
                )

            # ------------------------------------------------------------------
            # Transformer-AE
            # ------------------------------------------------------------------
            if seq_train_norm.shape[0] == 0 or seq_val_norm.shape[0] == 0:
                print(f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=TransformerAE skipped (empty normal-only split)")
                rows.append({"baseline": "TransformerAE", "seed": seed, "fold": fold_idx,
                             "auroc": 0.0, "auprc": 0.0, "f1": 0.0, "threshold": 0.5})
                _save_predictions(
                    pred_dir, "TransformerAE", seed, fold_idx,
                    np.array([]), np.array([]),
                )
            else:
                tf_ae = TransformerAE()
                train_ae(
                    tf_ae,
                    _seq_loader(seq_train_norm, lbl_train_norm, shuffle=True),
                    _seq_loader(seq_val_norm, lbl_val_norm, shuffle=False),
                    device=device,
                    epochs=epochs,
                    lr=lr,
                    weight_decay=1e-5,
                    patience=patience,
                    verbose=False,
                )
                scores_val_tf, labels_val_tf = score_ae(tf_ae, _full_seq_loader("val"), device=device)
                scores_test_tf, labels_test_tf = score_ae(tf_ae, _full_seq_loader("test"), device=device)
                auroc, auprc, f1, thr_tf = compute_metrics(scores_val_tf, labels_val_tf, scores_test_tf, labels_test_tf)
                print(
                    f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=TransformerAE "
                    f"AUROC={auroc:.4f} AUPRC={auprc:.4f} F1={f1:.4f}"
                )
                rows.append(
                    dict(baseline="TransformerAE", seed=seed, fold=fold_idx,
                         auroc=auroc, auprc=auprc, f1=f1, threshold=thr_tf)
                )
                _save_predictions(
                    pred_dir, "TransformerAE", seed, fold_idx,
                    labels_test_tf, scores_test_tf,
                )

            # ------------------------------------------------------------------
            # Deep SVDD
            # ------------------------------------------------------------------
            if flat_train_norm.shape[0] == 0 or flat_val_norm.shape[0] == 0:
                print(f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=DeepSVDD skipped (empty normal-only split)")
                rows.append({"baseline": "DeepSVDD", "seed": seed, "fold": fold_idx,
                             "auroc": 0.0, "auprc": 0.0, "f1": 0.0, "threshold": 0.5})
                _save_predictions(
                    pred_dir, "DeepSVDD", seed, fold_idx,
                    np.array([]), np.array([]),
                )
            else:
                svdd_net = DeepSVDDNet()
                svdd_net, c = train_deep_svdd(
                    svdd_net,
                    _flat_loader(flat_train_norm, lbl_train_norm, shuffle=True),
                    _flat_loader(flat_val_norm, lbl_val_norm, shuffle=False),
                    device=device,
                    epochs=epochs,
                    lr=lr,
                    weight_decay=1e-6,
                    patience=patience,
                    verbose=False,
                )
                scores_val_svdd, labels_val_svdd = score_deep_svdd(
                    svdd_net, c, _full_flat_loader("val"), device=device
                )
                scores_test_svdd, labels_test_svdd = score_deep_svdd(
                    svdd_net, c, _full_flat_loader("test"), device=device
                )
                auroc, auprc, f1, thr_svdd = compute_metrics(scores_val_svdd, labels_val_svdd, scores_test_svdd, labels_test_svdd)
                print(
                    f"[seed {seed} | fold {fold_idx}/{k_folds}] baseline=DeepSVDD "
                    f"AUROC={auroc:.4f} AUPRC={auprc:.4f} F1={f1:.4f}"
                )
                rows.append(
                    dict(baseline="DeepSVDD", seed=seed, fold=fold_idx,
                         auroc=auroc, auprc=auprc, f1=f1, threshold=thr_svdd)
                )
                _save_predictions(
                    pred_dir, "DeepSVDD", seed, fold_idx,
                    labels_test_svdd, scores_test_svdd,
                )

    # ------------------------------------------------------------------
    # Write results
    # ------------------------------------------------------------------
    out_csv = Path(args.out)
    out_md = out_csv.with_suffix(".md")
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with open(out_csv, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["baseline", "seed", "fold", "auroc", "auprc", "f1", "threshold"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nCSV written to {out_csv}")

    baselines_order = ["IsolationForest", "LSTMAE", "CNNAE", "TransformerAE", "DeepSVDD"]
    metrics = ["auroc", "auprc", "f1"]

    with open(out_md, "w") as fh:
        fh.write("# Baselines CV Results\n\n")
        fh.write("## Per-(seed, fold) results\n\n")
        fh.write("| baseline | seed | fold | auroc | auprc | f1 | threshold |\n")
        fh.write("|---|---|---|---|---|---|---|\n")
        for row in rows:
            fh.write(
                f"| {row['baseline']} | {row['seed']} | {row['fold']} "
                f"| {row['auroc']:.4f} | {row['auprc']:.4f} "
                f"| {row['f1']:.4f} | {row['threshold']:.6f} |\n"
            )

        fh.write(
            "\n## Summary (mean ± std per baseline, over seeds × folds)\n\n"
        )
        fh.write("| baseline | auroc | auprc | f1 |\n")
        fh.write("|---|---|---|---|\n")
        for name in baselines_order:
            subset = [r for r in rows if r["baseline"] == name]
            if not subset:
                continue
            parts = []
            for m in metrics:
                vals = np.array([r[m] for r in subset])
                parts.append(f"{vals.mean():.4f} ± {vals.std():.4f}")
            fh.write(f"| {name} | {' | '.join(parts)} |\n")

    print(f"Markdown written to {out_md}")


def _parse_seeds(raw: str) -> list[int]:
    return [int(s.strip()) for s in raw.split(",") if s.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentGuard baseline CV driver")
    parser.add_argument("--config", required=True, help="Path to config.yml")
    parser.add_argument(
        "--out", default="results/baselines.csv", help="Output CSV path"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Smoke-run mode: 3 epochs per model"
    )
    parser.add_argument(
        "--seeds",
        default="42,1337,2024",
        help="Comma-separated list of seeds to iterate (default: 42,1337,2024)",
    )
    args = parser.parse_args()
    args.seeds = _parse_seeds(args.seeds)
    run(args)


if __name__ == "__main__":
    main()
