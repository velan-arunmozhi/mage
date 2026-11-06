#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=04:00:00
#SBATCH --job-name=gb10-round3
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round3-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round3-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/14-round3.sh
