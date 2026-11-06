#!/bin/bash
# Relaunch the CUDA-graph NVFP4 server and measure a filled long prompt plus a few checked tasks.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
LOCAL=/tmp/models/qwen36-nvfp4

ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
  kill -9 "${pid}" 2>/dev/null || true
done
sleep 2

echo "LAUNCH longcontext $(date -Is)"
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
  --bind "${ROOT}/tmp:/tmp" \
  --bind /tmp/models:/tmp/models \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  --env VLLM_CACHE_ROOT=/root/.cache/vllm \
  --env VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
  "${IMG}" vllm serve "${LOCAL}" \
    --served-model-name "${MODEL}" \
    --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len 131072 \
    --max-num-seqs 8 \
    --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.26 \
    --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --moe-backend marlin \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --safetensors-load-strategy eager \
    --reasoning-parser qwen3 \
    > "${ROOT}/logs/vllm-longcontext.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"

for i in $(seq 1 900); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "READY longcontext after $((i * 2))s"
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED longcontext"
    tail -30 "${ROOT}/logs/vllm-longcontext.log" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
  if (( i % 20 == 0 )); then echo "waiting longcontext ${i}"; fi
  sleep 2
done

python3 "${ROOT}/scripts/long_and_quality.py" || echo "long/quality script failed" | tee -a "${ROOT}/failures.md"

if [[ -f "${ROOT}/state/vllm.pid" ]]; then
  kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
  kill -9 "${pid}" 2>/dev/null || true
done
echo "LONGCONTEXT DONE $(date -Is)"
