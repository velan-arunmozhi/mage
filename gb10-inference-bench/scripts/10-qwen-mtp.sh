#!/bin/bash
# MTP on the CUDA-graph Qwen3.6 configuration. Profile A only, 1 and 8 clients.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
LOCAL=/tmp/models/qwen36-nvfp4

stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 4
}

launch() {
  local tokens="$1"
  stop_all
  echo "LAUNCH mtp-${tokens} $(date -Is) free=$(awk '/Mem:/ {print $4}' /proc/meminfo)"
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
      --spec-method mtp \
      --spec-tokens "${tokens}" \
      > "${ROOT}/logs/vllm-mtp-graphs-${tokens}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY mtp-${tokens} after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED mtp-${tokens}"
      tail -30 "${ROOT}/logs/vllm-mtp-graphs-${tokens}.log" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then echo "waiting mtp-${tokens} ${i}"; tail -1 "${ROOT}/logs/vllm-mtp-graphs-${tokens}.log" || true; fi
    sleep 2
  done
  echo "TIMEOUT mtp-${tokens}" | tee -a "${ROOT}/failures.md"
  stop_all
  return 1
}

bench() {
  local tokens="$1"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${MODEL}" \
    --hf-id "${MODEL}" \
    --quantization NVFP4 \
    --engine vllm \
    --engine-version "vllm 0.28.0 cuda-graphs mtp" \
    --profiles A \
    --concurrencies 1,8 \
    --mode sustained \
    --duration 60 \
    --warmup 1 \
    --timeout 1800 \
    --tag "qwen36-nvfp4-graphs-mtp${tokens}" \
    --context-configured 131072 \
    --kv-cache fp8 \
    --attention flashinfer \
    --moe-backend marlin \
    --mtp mtp \
    --draft-tokens "${tokens}" \
    --thinking off \
    --raw-dir "${ROOT}/raw"
}

for tokens in 1 3; do
  if launch "${tokens}"; then
    grep -E "speculative|KV cache size|Model loading took" "${ROOT}/logs/vllm-mtp-graphs-${tokens}.log" | tee -a "${ROOT}/raw/mtp-notes.txt" || true
    bench "${tokens}" || echo "bench mtp ${tokens} failed" | tee -a "${ROOT}/failures.md"
  fi
  stop_all
done
echo "MTP DONE $(date -Is)"
