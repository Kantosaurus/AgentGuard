"""
AgentGuard — Sweep Runner

Orchestrates phased Optuna hyperparameter search.

Usage:
    python -m sweep.run_sweep --phase 1              # Architecture (100 trials)
    python -m sweep.run_sweep --phase 2              # Training dynamics (60 trials, 3-fold)
    python -m sweep.run_sweep --phase 3              # Loss + data (60 trials, 3-fold)
    python -m sweep.run_sweep --phase 4              # Fine-tune top-K (5-fold)
    python -m sweep.run_sweep --phase all            # Sequential all phases
    python -m sweep.run_sweep --phase 1 --n-trials 50
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
import optuna
import yaml

from sweep.objective import create_objective, _set_seed, _run_single_fold
from sweep.config_override import override_config


RESULTS_DIR = Path("sweep/results")
DB_PATH = RESULTS_DIR / "optuna.db"


def _get_storage_url():
    """Return Optuna storage URL. OPTUNA_STORAGE env var wins (e.g. Postgres);
    otherwise use the local SQLite file. SQLite WAL mode is a separate
    one-time setup via: sqlite3 sweep/results/optuna.db "PRAGMA journal_mode=WAL;"
    """
    env = os.environ.get("OPTUNA_STORAGE")
    if env:
        return env
    return f"sqlite:///{DB_PATH}"

PHASE_DEFAULTS = {
    1: {"n_trials": 100, "n_folds": 0, "study_name": "phase1_architecture"},
    2: {"n_trials": 60,  "n_folds": 3, "study_name": "phase2_training"},
    3: {"n_trials": 60,  "n_folds": 3, "study_name": "phase3_loss_data"},
    4: {"n_trials": 10,  "n_folds": 5, "study_name": "phase4_finetune"},
}


def load_base_config(config_path="config.yml"):
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_best_params_path(phase):
    return RESULTS_DIR / f"best_params_phase{phase}.json"


def _load_best_params(phase):
    """Load best params from a completed phase."""
    path = _get_best_params_path(phase)
    if not path.exists():
        raise FileNotFoundError(f"No best params for phase {phase}. Run phase {phase} first.")
    with open(path) as f:
        return json.load(f)


def _save_results(study, phase):
    """Save best params JSON and CSV results for a study."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Best params
    best_path = _get_best_params_path(phase)
    with open(best_path, "w") as f:
        json.dump(study.best_trial.params, f, indent=2)
    print(f"Best params saved to {best_path}")

    # CSV with all trials
    csv_path = RESULTS_DIR / f"trials_phase{phase}.csv"
    df = study.trials_dataframe()
    df.to_csv(csv_path, index=False)
    print(f"All trials saved to {csv_path}")


def run_phase(phase, base_config, n_trials=None, n_folds=None):
    """Run a single sweep phase."""
    defaults = PHASE_DEFAULTS[phase]
    n_trials = n_trials or defaults["n_trials"]
    n_folds = n_folds if n_folds is not None else defaults["n_folds"]
    study_name = defaults["study_name"]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    storage = _get_storage_url()

    # Load locked params from prior phases
    best_params = {}
    if phase == 2:
        best_params = _load_best_params(1)
    elif phase == 3:
        p1 = _load_best_params(1)
        p2 = _load_best_params(2)
        best_params = {**p1, **p2}

    print(f"\n{'='*60}")
    print(f"Phase {phase}: {study_name}")
    print(f"  Trials: {n_trials}, Folds: {n_folds or 'single split'}")
    if best_params:
        print(f"  Locked params from prior phases: {len(best_params)} keys")
    print(f"{'='*60}\n")

    pruner = optuna.pruners.MedianPruner(
        n_startup_trials=5, n_warmup_steps=10,
    )
    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        pruner=pruner,
        load_if_exists=True,
    )

    objective = create_objective(base_config, phase, best_params, n_folds)
    study.optimize(objective, n_trials=n_trials)

    print(f"\nBest trial: {study.best_trial.number}")
    print(f"  Value (AUROC): {study.best_value:.4f}")
    print(f"  Params: {study.best_trial.params}")

    # Phase-level summary log
    log_cfg = base_config.get("logging", {})
    if log_cfg.get("enabled", False):
        from utils.logging import setup_run_logger
        phase_logger, _ = setup_run_logger(
            "sweep", base_config, log_dir=log_cfg.get("log_dir", "logs"), phase=phase,
        )
        phase_logger.info(f"Trials: {n_trials}, Folds: {n_folds or 'single split'}")
        phase_logger.info(f"\nBest trial: {study.best_trial.number}")
        phase_logger.info(f"  Value (AUROC): {study.best_value:.4f}")
        phase_logger.info(f"  Params: {study.best_trial.params}")

    _save_results(study, phase)
    return study


def run_phase4(base_config, n_folds=5, top_k=5):
    """Phase 4: Full CV on top-K configs from Phase 3."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    storage = _get_storage_url()

    # Load Phase 3 study to get top-K trials
    study3 = optuna.load_study(
        study_name=PHASE_DEFAULTS[3]["study_name"], storage=storage,
    )
    sorted_trials = sorted(study3.trials, key=lambda t: t.value or 0, reverse=True)
    top_trials = sorted_trials[:top_k]

    print(f"\n{'='*60}")
    print(f"Phase 4: Full {n_folds}-fold CV on top-{top_k} configs")
    print(f"{'='*60}\n")

    import torch
    from main import make_stratified_folds

    # Phase 4 summary logger
    phase4_logger = None
    log_cfg = base_config.get("logging", {})
    if log_cfg.get("enabled", False):
        from utils.logging import setup_run_logger
        phase4_logger, _ = setup_run_logger(
            "sweep", base_config, log_dir=log_cfg.get("log_dir", "logs"), phase=4,
        )

    results = []
    for rank, trial in enumerate(top_trials):
        print(f"\n--- Config {rank+1}/{top_k} (Phase 3 trial {trial.number}, AUROC={trial.value:.4f}) ---")

        config = override_config(base_config, trial.params)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _set_seed(42)

        data_cfg = config["data"]
        attacked = data_cfg["attacked_agents"]
        control = data_cfg["control_agents"]
        folds = make_stratified_folds(attacked, control, n_folds)

        fold_aurocs = []
        for fold_idx in range(n_folds):
            test_agents = folds[fold_idx]
            val_agents = folds[(fold_idx + 1) % n_folds]
            train_agents = []
            for j in range(n_folds):
                if j != fold_idx and j != (fold_idx + 1) % n_folds:
                    train_agents.extend(folds[j])

            auroc = _run_single_fold(
                config, train_agents, val_agents, device,
                checkpoint_suffix=f"phase4_r{rank}_f{fold_idx}",
            )
            fold_aurocs.append(auroc)
            print(f"  Fold {fold_idx+1}: AUROC={auroc:.4f}")

        mean_auroc = float(np.mean(fold_aurocs))
        std_auroc = float(np.std(fold_aurocs))
        print(f"  Mean AUROC: {mean_auroc:.4f} +/- {std_auroc:.4f}")

        if phase4_logger:
            phase4_logger.info(
                f"Config {rank+1}/{top_k} (trial {trial.number}): "
                f"Mean AUROC={mean_auroc:.4f} +/- {std_auroc:.4f}  "
                f"Folds={fold_aurocs}"
            )

        results.append({
            "rank": rank + 1,
            "phase3_trial": trial.number,
            "params": trial.params,
            "fold_aurocs": fold_aurocs,
            "mean_auroc": mean_auroc,
            "std_auroc": std_auroc,
        })

    # Save results
    results_path = RESULTS_DIR / "phase4_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nPhase 4 results saved to {results_path}")

    # Summary
    best = max(results, key=lambda r: r["mean_auroc"])
    print(f"\nBest config: rank {best['rank']} (trial {best['phase3_trial']})")
    print(f"  Mean AUROC: {best['mean_auroc']:.4f} +/- {best['std_auroc']:.4f}")

    if phase4_logger:
        phase4_logger.info(f"\nBest config: rank {best['rank']} (trial {best['phase3_trial']})")
        phase4_logger.info(f"  Mean AUROC: {best['mean_auroc']:.4f} +/- {best['std_auroc']:.4f}")

    # Save best params
    best_path = _get_best_params_path(4)
    with open(best_path, "w") as f:
        json.dump(best["params"], f, indent=2)

    return results


def main():
    parser = argparse.ArgumentParser(description="AgentGuard hyperparameter sweep")
    parser.add_argument("--phase", required=True,
                        help="Phase to run: 1, 2, 3, 4, or all")
    parser.add_argument("--n-trials", type=int, default=None,
                        help="Override number of trials")
    parser.add_argument("--config", default="config.yml",
                        help="Path to base config file")
    args = parser.parse_args()

    base_config = load_base_config(args.config)

    if args.phase == "all":
        for phase in [1, 2, 3]:
            run_phase(phase, base_config, n_trials=args.n_trials)
        run_phase4(base_config)
    elif args.phase == "4":
        run_phase4(base_config)
    else:
        phase = int(args.phase)
        run_phase(phase, base_config, n_trials=args.n_trials)


if __name__ == "__main__":
    main()
