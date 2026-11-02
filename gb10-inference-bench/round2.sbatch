#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=04:00:00
#SBATCH --job-name=gb10-round2
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round2-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-round2-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench

set -u
echo "${SLURM_JOB_ID}" > /scratch/scholar/billin19/gb10-inference-bench/JOBID
hostname -f > /scratch/scholar/billin19/gb10-inference-bench/HOSTNAME 2>/dev/null || hostname > /scratch/scholar/billin19/gb10-inference-bench/HOSTNAME
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/12-round2.sh
