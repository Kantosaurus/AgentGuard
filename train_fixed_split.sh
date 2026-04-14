# run_pipeline.sh
# Bash script to run full pipeline of main.py

# Stop script if any command fails
set -e

echo "=== Running fixed split pipeline ==="
# 1. Preprocess raw JSONL into tensors
echo "=== Preprocess Data ==="
python main.py --mode preprocess

# 2. Train on fixed split
echo "=== Train on Fixd Splits ==="
python main.py --mode train

# 3. Evaluate on held-out test split
echo "=== Evaluate Model ==="
python main.py --mode eval

echo "=== Fixed split pipeline complete ==="