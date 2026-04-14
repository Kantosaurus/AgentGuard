# run_pipeline.sh
# Bash script to run full pipeline of main.py

# Stop script if any command fails
set -e

# Optional: Cross-validation pipeline
echo "=== Running cross-validation pipeline ==="

echo "=== Preprocess Data ==="
python main.py --mode preprocess

echo "=== Run Cross Validation ==="
# 2. Run cross-validation (5 folds)
python main.py --mode cv

echo "=== Cross-validation pipeline complete ==="