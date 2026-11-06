#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --nodelist=scholar-k077
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8000M
#SBATCH --time=00:20:00
#SBATCH --job-name=gb10-clean
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-clean-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-clean-%j.err
set -u
echo "CLEAN START $(date -Is) $(hostname)"
df -h /tmp
if [[ -d /tmp/models/nemotron-nvfp4 && ! -f /tmp/models/nemotron-nvfp4/config.json ]]; then
  echo "removing poisoned model dir"
  rm -rf /tmp/models/nemotron-nvfp4
fi
df -h /tmp
echo "CLEAN DONE $(date -Is)"
