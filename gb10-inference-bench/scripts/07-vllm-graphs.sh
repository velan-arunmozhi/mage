#!/bin/bash
# Eager decode was ~11 tok/s per stream and still linear at 12 clients with low GPU use.
# Retry the same NVFP4 server with CUDA graphs enabled.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
LOCAL=/tmp/models/qwen36-nvfp4

stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  sleep 2
}

# Earlier serves left EngineCore processes behind after the Apptainer parent exited.
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
  kill -9 "${pid}" 2>/dev/null || true
done
sleep 3
echo "MEM $(free -g | awk '/Mem:/ {print $4\"Gi free\"}')"
echo "LAUNCH graphs $(date -Is)"
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
    --max-num-seqs 16 \
    --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.26 \
    --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --moe-backend marlin \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --safetensors-load-strategy eager \
    --reasoning-parser qwen3 \
    > "${ROOT}/logs/vllm-graphs-131k.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"

ready=0
for i in $(seq 1 900); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "READY graphs after $((i * 2))s"
    ready=1
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED graphs"
    tail -40 "${ROOT}/logs/vllm-graphs-131k.log" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
  if (( i % 20 == 0 )); then
    echo "waiting graphs ${i}"
    tail -1 "${ROOT}/logs/vllm-graphs-131k.log" || true
  fi
  sleep 2
done
if [[ "${ready}" != 1 ]]; then
  echo "TIMEOUT graphs" | tee -a "${ROOT}/failures.md"
  stop_server
  exit 1
fi
grep -E "KV cache size|Maximum concurrency|Model loading took|CUDA graph|cudagraph" "${ROOT}/logs/vllm-graphs-131k.log" | tee "${ROOT}/raw/qwen36-graphs-kv.txt" || true

python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --model "${MODEL}" \
  --hf-id "${MODEL}" \
  --quantization NVFP4 \
  --engine vllm \
  --engine-version "vllm 0.28.0 cuda-graphs" \
  --profiles A,B \
  --concurrencies 1,4,8,12 \
  --mode sustained \
  --duration 60 \
  --warmup 1 \
  --timeout 1800 \
  --tag qwen36-nvfp4-graphs-131k \
  --context-configured 131072 \
  --kv-cache fp8 \
  --attention flashinfer \
  --moe-backend marlin \
  --mtp off \
  --thinking off \
  --raw-dir "${ROOT}/raw" || echo "graph bench failed" | tee -a "${ROOT}/failures.md"

stop_server
echo "GRAPHS DONE $(date -Is)"
