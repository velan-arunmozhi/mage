#!/bin/bash
# Capture the compute-node environment. Safe to re-run.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
OUT="${ROOT}/logs/probe.txt"
{
  echo "===== DATE ====="
  date -Is
  echo "===== HOST ====="
  hostname -f || hostname
  uname -a
  echo "===== SLURM ====="
  echo "JOB=${SLURM_JOB_ID:-} PARTITION=${SLURM_JOB_PARTITION:-} NODELIST=${SLURM_JOB_NODELIST:-}"
  echo "CPUS=${SLURM_CPUS_ON_NODE:-} MEM=${SLURM_MEM_PER_NODE:-}"
  (squeue -j "${SLURM_JOB_ID:-}" -o "%i %P %u %T %M %L %C %m %b %R" || true)
  echo "===== CPU ====="
  nproc
  lscpu | head -40
  echo "===== MEM ====="
  free -h
  echo "===== DF ====="
  df -h
  echo "===== CGROUP ====="
  cat /proc/self/cgroup || true
  if [[ -f /sys/fs/cgroup/memory.max ]]; then
    echo -n "memory.max "; cat /sys/fs/cgroup/memory.max
    echo -n "memory.current "; cat /sys/fs/cgroup/memory.current
  fi
  find /sys/fs/cgroup -name memory.max -readable 2>/dev/null | head -20 | while read -r f; do
    echo "$f $(cat "$f" 2>/dev/null)"
  done
  echo "===== NVIDIA ====="
  nvidia-smi || true
  nvidia-smi --query-gpu=name,compute_cap,memory.total,memory.used,driver_version,clocks.max.sm,power.limit --format=csv || true
  echo "===== NVCC ====="
  nvcc --version || true
  echo "===== PYTHON ====="
  python3 --version || true
  echo "===== APPTAINER ====="
  apptainer --version || true
  echo "===== LLAMA ====="
  "${LLAMA_BENCH}" --version || true
  echo "===== DEVICES ====="
  "${LLAMA_BENCH}" --list-devices || true
} > "${OUT}" 2>&1
cp "${OUT}" "${ROOT}/raw/probe.txt"
echo "probe written ${OUT}"
