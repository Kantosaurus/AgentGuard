# Bash script to run full pipeline of main.py

# Stop script if any command fails
set -e

echo "=== Running Hyperparameter Tuning Scripts --> Cross-validation pipeline ==="
python -m sweep.run_sweep --phase all

echo "=== Apply Best Parameters found after Hyperparameter tuning ==="
python utils\apply_best_params.py

echo "=== Preprocess Data ==="
python main.py --mode preprocess

echo "=== Run Cross Validation ==="
# 2. Run cross-validation (5 folds)
python main.py --mode cv
