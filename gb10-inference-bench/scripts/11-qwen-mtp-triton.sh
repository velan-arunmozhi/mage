#!/bin/bash
# MTP draft MoE is unquantized. Marlin rejected it.
# Keep Marlin for the NVFP4 target and Triton for the MTP head, as in the model card.
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
  local spec
  spec="{\"method\":\"mtp\",\"num_speculative_tokens\":${tokens},\"moe_backend\":\"triton\"}"
  echo "LAUNCH mtp-triton-${tokens} $(date -Is)"
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
      --speculative-config "${spec}" \
      > "${ROOT}/logs/vllm-mtp-triton-${tokens}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY mtp-triton-${tokens} after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED mtp-triton-${tokens}"
      tail -25 "${ROOT}/logs/vllm-mtp-triton-${tokens}.log" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then echo "waiting mtp-triton-${tokens} ${i}"; fi
    sleep 2
  done
  echo "TIMEOUT mtp-triton-${tokens}" | tee -a "${ROOT}/failures.md"
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
    --engine-version "vllm 0.28.0 cuda-graphs mtp-triton" \
    --profiles A \
    --concurrencies 1,8 \
    --mode sustained \
    --duration 60 \
    --warmup 1 \
    --timeout 1800 \
    --tag "qwen36-graphs-mtp${tokens}-triton" \
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
    bench "${tokens}" || echo "bench failed ${tokens}" | tee -a "${ROOT}/failures.md"
  fi
  stop_all
done
echo "MTP TRITON DONE $(date -Is)"
