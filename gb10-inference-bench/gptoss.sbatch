#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --nodelist=scholar-k077
#SBATCH --dependency=afterany:481731
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=03:00:00
#SBATCH --job-name=gb10-gptoss
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-gptoss-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-gptoss-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/21-gptoss.sh
