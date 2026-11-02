#!/bin/bash
# Profile A/B at 24 clients. 16 was still faster than 12, so the peak is not established.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/13-c24.out"
exec > >(tee -a "${LOG}") 2>&1
echo "C24 START $(date -Is) $(hostname)"
mkdir -p /tmp/vllm-apptainer /tmp/models
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
  mkdir -p "${QWEN_LOCAL}"
  cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
fi

stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 3
}

launch() {
  local util="$1"
  stop_all
  echo "LAUNCH util=${util} seqs=24 $(date -Is)"
  free -h
  local spec='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
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
    "${IMG}" vllm serve "${QWEN_LOCAL}" \
      --served-model-name "${QWEN_MODEL}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs 24 --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer --moe-backend marlin \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager --reasoning-parser qwen3 \
      --speculative-config "${spec}" \
      > "${ROOT}/logs/vllm-c24-${util}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY util=${util}"
      grep "KV cache size" "${ROOT}/logs/vllm-c24-${util}.log" | tee "${ROOT}/raw/c24-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED util=${util}"
      grep -E "ValueError|No available|Free memory" "${ROOT}/logs/vllm-c24-${util}.log" | tail -5 | tee -a "${ROOT}/failures.md"
      return 1
    fi
    sleep 2
  done
  return 1
}

if ! launch 0.40; then
  launch 0.45 || { echo "24-seq server failed" | tee -a "${ROOT}/failures.md"; exit 1; }
fi
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --model "${QWEN_MODEL}" --hf-id "${QWEN_MODEL}" --quantization NVFP4 \
  --engine vllm --engine-version "vllm 0.28.0 cuda-graphs mtp3 seq24" \
  --profiles A,B --concurrencies 24 --mode sustained --duration 60 --warmup 1 \
  --timeout 1800 --tag qwen36-mtp3-c24 --context-configured 131072 \
  --kv-cache fp8 --attention flashinfer --moe-backend marlin \
  --mtp mtp --draft-tokens 3 --thinking off --raw-dir "${ROOT}/raw"
stop_all
echo "C24 DONE $(date -Is)"
