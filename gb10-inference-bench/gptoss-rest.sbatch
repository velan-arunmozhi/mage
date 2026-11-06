#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --nodelist=scholar-k077
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=02:30:00
#SBATCH --job-name=gb10-gptrest
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-gptrest-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-gptrest-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
bash /scratch/scholar/billin19/gb10-inference-bench/scripts/22-gptoss-rest.sh
