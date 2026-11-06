#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=02:30:00
#SBATCH --job-name=gb10-round4b
#SBATCH --dependency=afterany:481526
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round4b-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round4b-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/17-round4b.sh
