#!/bin/bash
#SBATCH --job-name=SelectiveMagnoViT-Preprocess
#SBATCH --output=logs/slurm/preprocess_%j.out
#SBATCH --error=logs/slurm/preprocess_%j.err
#SBATCH --mail-type=FAIL,END
#SBATCH --mail-user=horaja@cs.cmu.edu
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32gb
#SBATCH --time=12:00:00
#SBATCH --partition=gpu

# Exit on error
set -e

echo "=========================================="
echo "SLURM Job Information"
echo "=========================================="
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $HOSTNAME"
echo "Start time: $(date)"
echo "=========================================="

# Setup environment
echo "Initializing mamba..."
set +e  # Disable exit on error temporarily
eval "$(mamba shell hook --shell bash)" 2>&1
HOOK_EXIT=$?
set -e  # Re-enable exit on error
echo "Mamba hook exit code: $HOOK_EXIT"

echo "Updating/creating environment..."
mamba env update -f environment.yml || mamba env create -f environment.yml -y

echo "Activating environment..."
mamba activate drawings
echo "Environment activated successfully"

# Verify GPU
nvidia-smi

# Change to project directory
cd $SLURM_SUBMIT_DIR

# Create logs directory
mkdir -p logs/slurm

# Run preprocessing
python scripts/preprocess.py \
    --config configs/base_config.yml \
    --raw_data_root "${RAW_DATA_ROOT:-data/raw_dataset}" \
    --preprocessed_root "${PREPROCESSED_ROOT:-data/preprocessed}" \
    --splits train val \
    ${EXTRA_ARGS}

echo "=========================================="
echo "Preprocessing completed at: $(date)"
echo "=========================================="
