#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=04:00:00
#SBATCH --job-name=gb10-hgpt
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-hgpt-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-hgpt-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/27-harbor-gpt.sh
