"""
AgentGuard — Post-Sweep Analysis

Load Optuna studies and generate summary reports, importance rankings,
and top-config comparison tables.

Usage:
    python -m sweep.analysis --phase 1
    python -m sweep.analysis --phase all
"""

import argparse
from pathlib import Path

import optuna

RESULTS_DIR = Path("sweep/results")
DB_PATH = RESULTS_DIR / "optuna.db"

STUDY_NAMES = {
    1: "phase1_architecture",
    2: "phase2_training",
    3: "phase3_loss_data",
}


def analyze_phase(phase):
    """Print analysis for a single phase."""
    storage = f"sqlite:///{DB_PATH}"
    study_name = STUDY_NAMES[phase]

    try:
        study = optuna.load_study(study_name=study_name, storage=storage)
    except KeyError:
        print(f"Phase {phase} study '{study_name}' not found in database.")
        return

    print(f"\n{'='*60}")
    print(f"Phase {phase}: {study_name}")
    print(f"{'='*60}")

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]

    print(f"  Total trials:    {len(study.trials)}")
    print(f"  Completed:       {len(completed)}")
    print(f"  Pruned:          {len(pruned)}")

    if not completed:
        print("  No completed trials to analyze.")
        return

    print(f"  Best trial:      {study.best_trial.number}")
    print(f"  Best AUROC:      {study.best_value:.4f}")
    print(f"  Best params:")
    for k, v in study.best_trial.params.items():
        print(f"    {k}: {v}")

    # Hyperparameter importance
    try:
        importances = optuna.importance.get_param_importances(study)
        print(f"\n  Hyperparameter importance:")
        for param, imp in importances.items():
            bar = "#" * int(imp * 40)
            print(f"    {param:30s} {imp:.4f} {bar}")
    except Exception as e:
        print(f"\n  Could not compute importance: {e}")

    # Top 10 configs
    sorted_trials = sorted(completed, key=lambda t: t.value or 0, reverse=True)
    top10 = sorted_trials[:10]
    print(f"\n  Top 10 configs:")
    print(f"  {'Rank':>4s} {'Trial':>6s} {'AUROC':>8s}  Key Params")
    print(f"  {'-'*4} {'-'*6} {'-'*8}  {'-'*40}")
    for rank, trial in enumerate(top10, 1):
        # Show a few key params
        params_str = ", ".join(f"{k}={v}" for k, v in list(trial.params.items())[:4])
        print(f"  {rank:4d} {trial.number:6d} {trial.value:8.4f}  {params_str}")


def main():
    parser = argparse.ArgumentParser(description="AgentGuard sweep analysis")
    parser.add_argument("--phase", default="all", help="Phase to analyze: 1, 2, 3, or all")
    args = parser.parse_args()

    if args.phase == "all":
        for phase in [1, 2, 3]:
            analyze_phase(phase)
    else:
        analyze_phase(int(args.phase))


if __name__ == "__main__":
    main()
