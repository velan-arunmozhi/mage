#!/bin/bash
#SBATCH --account=scholar
#SBATCH --partition=spark-batch
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=20
#SBATCH --mem=120500M
#SBATCH --time=04:00:00
#SBATCH --job-name=gb10-inf-bench
#SBATCH --output=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-%j.out
#SBATCH --error=/scratch/scholar/billin19/gb10-inference-bench/logs/slurm-%j.err
#SBATCH --chdir=/scratch/scholar/billin19/gb10-inference-bench
#SBATCH --signal=B:USR1@180

set -u
ROOT=/scratch/scholar/billin19/gb10-inference-bench
mkdir -p "${ROOT}/logs" "${ROOT}/queue/pending" "${ROOT}/queue/running" "${ROOT}/queue/done" "${ROOT}/raw" "${ROOT}/state"
echo "${SLURM_JOB_ID}" > "${ROOT}/JOBID"
hostname -f > "${ROOT}/HOSTNAME" 2>/dev/null || hostname > "${ROOT}/HOSTNAME"
date -Is > "${ROOT}/JOB_START"

cleanup() {
  echo "cleanup $(date -Is)" >> "${ROOT}/logs/worker.log"
  if [[ -f "${ROOT}/state/llama-server.pid" ]]; then
    kill "$(cat "${ROOT}/state/llama-server.pid")" 2>/dev/null || true
  fi
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
  fi
  if [[ -f "${ROOT}/state/memwatch.pid" ]]; then
    kill "$(cat "${ROOT}/state/memwatch.pid")" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'touch "${ROOT}/STOP"; cleanup' USR1

echo "worker start $(date -Is) job=${SLURM_JOB_ID}" >> "${ROOT}/logs/worker.log"
bash "${ROOT}/scripts/00-probe.sh" >> "${ROOT}/logs/worker.log" 2>&1 || echo "probe failed" >> "${ROOT}/logs/worker.log"
bash "${ROOT}/scripts/02-llama-baseline.sh" >> "${ROOT}/logs/02-llama-baseline.out" 2>&1 || echo "baseline failed" >> "${ROOT}/logs/worker.log"
bash "${ROOT}/scripts/03-vllm-qwen36.sh" >> "${ROOT}/logs/03-vllm-qwen36.out" 2>&1 || echo "vllm stage failed" >> "${ROOT}/logs/worker.log"

echo "entering queue $(date -Is)" >> "${ROOT}/logs/worker.log"
while [[ ! -f "${ROOT}/STOP" ]]; do
  next=""
  next=$(find "${ROOT}/queue/pending" -maxdepth 1 -type f -name '*.sh' 2>/dev/null | sort | head -1 || true)
  if [[ -z "${next}" ]]; then
    date -Is > "${ROOT}/state/heartbeat"
    sleep 5
    continue
  fi
  base=$(basename "${next}")
  mv "${next}" "${ROOT}/queue/running/${base}"
  echo "START ${base} $(date -Is)" >> "${ROOT}/logs/worker.log"
  set +e
  bash "${ROOT}/queue/running/${base}" > "${ROOT}/logs/${base}.out" 2> "${ROOT}/logs/${base}.err"
  ec=$?
  set +e
  echo "${ec}" > "${ROOT}/queue/done/${base}.exit"
  echo "END ${base} ${ec} $(date -Is)" >> "${ROOT}/logs/worker.log"
  mv "${ROOT}/queue/running/${base}" "${ROOT}/queue/done/${base}"
done
echo "worker stop $(date -Is)" >> "${ROOT}/logs/worker.log"
