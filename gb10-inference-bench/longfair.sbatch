#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=01:30:00
#SBATCH --job-name=gb10-longfair
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-longfair-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-longfair-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/15-long-fair.sh
