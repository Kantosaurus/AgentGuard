#!/usr/bin/env bash
# =============================================================================
# run_full_pipeline.sh — run the entire AgentGuard evaluation pipeline.
#
# Installs system + python deps, verifies GPUs, then runs Stages 1-4:
#   Stage 1: multiseed training   (3 seeds x 5 folds = 15 jobs, parallel)
#   Stage 2: baselines            (3 seeds parallel)
#   Stage 3: plots                (convergence, t-SNE, UMAP, attention, ROC/PR)
#   Stage 4: interpretability     (markdown reports + attribution heatmaps)
#
# Usage (run from repo root):
#   bash scripts/run_full_pipeline.sh                    # full pipeline
#   bash scripts/run_full_pipeline.sh --smoke-only       # smoke test only
#   bash scripts/run_full_pipeline.sh --skip-deps        # assume deps installed
#   bash scripts/run_full_pipeline.sh --skip-smoke       # skip smoke test
#   bash scripts/run_full_pipeline.sh --gpus 4           # override GPU count
#
# To run detached (survives SSH drop), wrap it:
#   nohup bash scripts/run_full_pipeline.sh > logs/pipeline.out 2>&1 &
#   echo $! > logs/pipeline.pid
#   disown
#   tail -f logs/pipeline.out            # watch progress
# =============================================================================

set -euo pipefail

SMOKE_ONLY=0
SKIP_DEPS=0
SKIP_SMOKE=0
N_GPUS="${N_GPUS:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke|--smoke-only) SMOKE_ONLY=1 ;;
        --skip-deps)          SKIP_DEPS=1  ;;
        --skip-smoke)         SKIP_SMOKE=1 ;;
        --gpus)               N_GPUS="$2"; shift ;;
        -h|--help)            sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
    shift
done

# ----------------------------------------------------------------------------
# Preamble
# ----------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p logs results/figures results/reports \
         predictions latents data/processed/checkpoints

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
MASTER_LOG="logs/pipeline_${TIMESTAMP}.log"

# Mirror all stdout/stderr to the master log while keeping terminal output.
exec > >(tee -a "$MASTER_LOG") 2>&1

step() { echo; echo "═══════════════════════════════════════════════════════════════════════"; echo "  $*"; echo "═══════════════════════════════════════════════════════════════════════"; }
note() { echo "  [note] $*"; }
die()  { echo "  [FATAL] $*" >&2; exit 1; }

T_START=$(date +%s)
trap 'rc=$?; T_END=$(date +%s); echo; echo "Pipeline exited with rc=$rc after $((T_END-T_START))s. Master log: $MASTER_LOG"' EXIT

echo "Repo:    $REPO_ROOT"
echo "Log:     $MASTER_LOG"
echo "Started: $(date)"

# ----------------------------------------------------------------------------
step "1/7  Install dependencies"
# ----------------------------------------------------------------------------
if [[ "$SKIP_DEPS" -eq 0 ]]; then
    if command -v apt-get >/dev/null 2>&1; then
        # Best effort: some minimal containers have broken sources; don't die.
        apt-get update -y || note "apt-get update failed; continuing"
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            tmux parallel rsync git ca-certificates \
            || note "some apt packages failed to install; continuing"
    else
        note "apt-get not present; skipping system package install"
    fi

    # Install torch FIRST from the CUDA index. PyPI's default torch wheels are
    # CPU-only, which would make torch.cuda.is_available() return False on
    # H200. We only install it if it's missing or is a CPU build.
    TORCH_CUDA_OK="$(python -c 'import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null && echo 1 || echo 0)"
    if [[ "$TORCH_CUDA_OK" != "1" ]]; then
        note "torch with CUDA not importable — installing from pytorch CUDA 12.4 index"
        pip install --no-cache-dir \
            --index-url https://download.pytorch.org/whl/cu124 \
            torch \
            || note "CUDA torch install failed; falling back to default index"
    else
        note "torch with CUDA already present; skipping torch reinstall"
    fi

    # Python deps needed by the pipeline (training, baselines, plots,
    # interpretability). Deliberately skip torch (already handled), and skip
    # streamlit/plotly/paramiko which are dashboard/SSH-live-mode only and
    # can pull in distutils-installed transitive deps (e.g. blinker) that
    # pip cannot upgrade cleanly on some Ubuntu base images.
    if [[ -f requirements.txt ]]; then
        grep -v -E '^\s*(torch|streamlit|plotly|paramiko)(\s|>|<|=|~|$)' requirements.txt \
            > /tmp/requirements_pipeline.txt || true
        echo "  installing (this can take 5-15 minutes on a fresh container):"
        cat /tmp/requirements_pipeline.txt | sed 's/^/    /'
        # --ignore-installed skips pip's uninstall-then-reinstall dance for
        # any package already present, sidestepping the distutils-uninstall
        # error class entirely. Dropped -q so progress is visible.
        pip install --no-cache-dir --progress-bar on --ignore-installed \
            -r /tmp/requirements_pipeline.txt \
            || note "requirements.txt install had errors; verifying imports next"
    fi
    # Belt-and-braces: umap-learn is often missing in minimal images.
    python -c "import umap" 2>/dev/null || pip install --no-cache-dir umap-learn
else
    note "--skip-deps: assuming system + python packages already installed"
fi

# Hard requirements from here on.
command -v parallel >/dev/null 2>&1 || die "GNU parallel is required"
command -v python   >/dev/null 2>&1 || die "python is required"
python -c "import torch, numpy, pandas, sklearn, matplotlib, seaborn, yaml" \
    || die "core python imports failed"

# ----------------------------------------------------------------------------
step "2/7  Verify CUDA + GPUs"
# ----------------------------------------------------------------------------
command -v nvidia-smi >/dev/null 2>&1 || die "nvidia-smi not found"
nvidia-smi --query-gpu=index,name,memory.total --format=csv

CUDA_OK="$(python -c 'import torch; print(int(torch.cuda.is_available()))')"
[[ "$CUDA_OK" == "1" ]] || die "torch.cuda.is_available() is False"

DETECTED_GPUS="$(python -c 'import torch; print(torch.cuda.device_count())')"
if [[ -z "$N_GPUS" ]]; then
    N_GPUS="$DETECTED_GPUS"
fi
# Cap at 7 per H200 setup.
if [[ "$N_GPUS" -gt 7 ]]; then
    note "Detected $DETECTED_GPUS GPUs; capping Stage 1 parallelism to 7"
    N_GPUS=7
fi
echo "  using $N_GPUS GPU(s) for Stage 1; $DETECTED_GPUS visible in total"

# ----------------------------------------------------------------------------
step "3/7  Sanity check: preprocessed data"
# ----------------------------------------------------------------------------
N_PT="$(ls data/processed/*.pt 2>/dev/null | wc -l)"
echo "  found $N_PT preprocessed .pt files (expect 20, one per agent)"
if [[ "$N_PT" -lt 20 ]]; then
    note "fewer than 20 .pt files — either rsync them up, or run:"
    note "    python main.py --mode preprocess"
    note "continuing; trainer will fail fast if data is missing"
fi

# ----------------------------------------------------------------------------
step "4/7  Smoke test (1 seed x 1 fold, --fast)"
# ----------------------------------------------------------------------------
if [[ "$SKIP_SMOKE" -eq 0 ]]; then
    CUDA_VISIBLE_DEVICES=0 python scripts/train_multiseed.py \
        --config config_best.yml --seeds 42 --folds 1 --fast --out_dir . \
        > logs/smoke.log 2>&1 \
        && echo "  smoke test passed (see logs/smoke.log)" \
        || { echo "  smoke test FAILED — tail of logs/smoke.log:"; tail -40 logs/smoke.log; die "smoke failed"; }
else
    note "--skip-smoke: skipping"
fi

if [[ "$SMOKE_ONLY" -eq 1 ]]; then
    echo
    echo "--smoke-only requested; stopping after smoke test."
    exit 0
fi

# ----------------------------------------------------------------------------
step "5/7  STAGE 1 — multiseed training (15 jobs on $N_GPUS GPUs)"
# ----------------------------------------------------------------------------
# {%} is parallel's slot number (1..N_GPUS); we map slot-1 -> CUDA device.
# --line-buffer keeps per-job output un-interleaved.
parallel -j "$N_GPUS" --colsep ' ' --line-buffer \
    --joblog logs/stage1_joblog.tsv \
    'CUDA_VISIBLE_DEVICES=$(({%}-1)) python scripts/train_multiseed.py \
        --config config_best.yml --seeds {1} --folds {2} --out_dir . \
        > logs/stage1_s{1}_f{2}.log 2>&1 && echo "  [done] seed={1} fold={2} on gpu=$(({%}-1))"' \
    ::: 42 1337 2024 ::: 1 2 3 4 5

N_CSV="$( ls logs/seed*_fold*_epochs.csv 2>/dev/null | wc -l )"
N_LAT="$( ls latents/agentguard_*.npz 2>/dev/null | wc -l )"
N_PRED="$( ls predictions/agentguard_*.npz 2>/dev/null | wc -l )"
N_CKPT="$( ls data/processed/checkpoints/model_seed*_fold*.pt 2>/dev/null | wc -l )"
echo
echo "  Stage 1 artifacts produced:"
echo "    epoch CSVs:    $N_CSV / 15"
echo "    latent NPZs:   $N_LAT / 15"
echo "    pred NPZs:     $N_PRED / 15"
echo "    checkpoints:   $N_CKPT / 15"
if [[ "$N_CSV" -lt 15 || "$N_LAT" -lt 15 || "$N_PRED" -lt 15 || "$N_CKPT" -lt 15 ]]; then
    note "Stage 1 incomplete. Inspect logs/stage1_joblog.tsv and per-job logs."
    note "Re-run failed jobs with: parallel --retry-failed --joblog logs/stage1_joblog.tsv"
    die "Stage 1 did not produce all 15 artifacts"
fi

# ----------------------------------------------------------------------------
step "6/7  STAGE 2 — baselines (3 seeds parallel)"
# ----------------------------------------------------------------------------
N_BASELINE_GPUS=3
[[ "$N_GPUS" -lt 3 ]] && N_BASELINE_GPUS="$N_GPUS"

parallel -j "$N_BASELINE_GPUS" --colsep ' ' --line-buffer \
    --joblog logs/stage2_joblog.tsv \
    'CUDA_VISIBLE_DEVICES=$(({%}-1)) python baselines/run_baselines.py \
        --config config_best.yml --seeds {1} \
        > logs/stage2_s{1}.log 2>&1 && echo "  [done] baselines seed={1} on gpu=$(({%}-1))"' \
    ::: 42 1337 2024

N_BASELINE_PRED=0
for slug in isolation_forest lstm_ae cnn_ae transformer_ae deep_svdd; do
    n="$( ls "predictions/${slug}"_*.npz 2>/dev/null | wc -l )"
    N_BASELINE_PRED=$((N_BASELINE_PRED + n))
    echo "    $slug: $n NPZs"
done
echo "  baseline predictions total: $N_BASELINE_PRED / 75"
if [[ "$N_BASELINE_PRED" -lt 60 ]]; then
    note "Baseline stage produced < 60/75 NPZs. Check logs/stage2_joblog.tsv."
    die "baseline stage incomplete"
fi

# ----------------------------------------------------------------------------
step "7/7  STAGES 3 + 4 — plots and interpretability"
# ----------------------------------------------------------------------------
python scripts/plots/run_all.py > logs/stage3.log 2>&1 \
    && echo "  plots done (logs/stage3.log)" \
    || { tail -40 logs/stage3.log; die "Stage 3 (plots) failed"; }

CUDA_VISIBLE_DEVICES=0 python scripts/generate_interpretability_reports.py \
    --config config_best.yml --seed 42 --fold 1 \
    --out_dir results/reports --n_per_category 3 \
    > logs/stage4.log 2>&1 \
    && echo "  interpretability reports done (logs/stage4.log)" \
    || { tail -40 logs/stage4.log; die "Stage 4 (reports) failed"; }

# ----------------------------------------------------------------------------
echo
echo "═══════════════════════════════════════════════════════════════════════"
echo "  PIPELINE COMPLETE"
echo "═══════════════════════════════════════════════════════════════════════"
echo
echo "Figures (results/figures/):"
ls -la results/figures/ 2>/dev/null | awk 'NR>1 {printf "  %s  %10s  %s\n", $6" "$7" "$8, $5, $9}' || true
echo
N_MD="$( find results/reports -name '*.md' 2>/dev/null | wc -l )"
echo "Interpretability reports: $N_MD markdown files under results/reports/"
echo
T_END=$(date +%s)
DUR=$((T_END - T_START))
printf "Total wall time: %dh %dm %ds\n" $((DUR/3600)) $(((DUR%3600)/60)) $((DUR%60))
echo
echo "To pull artifacts back to your local machine, from local:"
echo "  rsync -avz <host>:$(pwd)/results/ ./results/"
echo "  rsync -avz <host>:$(pwd)/logs/    ./logs/"
