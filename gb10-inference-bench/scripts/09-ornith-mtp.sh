#!/bin/bash
# Ornith 1.5 NVFP4 with one MTP draft token. Same kernels as the Qwen winner.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="ornith-ai/Ornith-1.5-35B-A3B-NVFP4"
LOCAL=/tmp/models/ornith-nvfp4

ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
  kill -9 "${pid}" 2>/dev/null || true
done
sleep 3

if [[ ! -f "${LOCAL}/config.json" ]]; then
  echo "DOWNLOAD ${MODEL} $(date -Is)"
  mkdir -p "${LOCAL}"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind /tmp/models:/tmp/models \
    --bind "${ROOT}/scripts:/scripts" \
    --env HF_HOME=/root/.cache/huggingface \
    --env HF_HUB_DISABLE_XET=1 \
    "${IMG}" python3 /scripts/download_ornith.py
fi
du -sh "${LOCAL}"

SPEC='{"method":"mtp","num_speculative_tokens":1,"moe_backend":"triton"}'
echo "LAUNCH ornith-mtp1 $(date -Is)"
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
    --max-model-len 131072 --max-num-seqs 12 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.26 --kv-cache-dtype fp8 \
    --attention-backend flashinfer --moe-backend marlin \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager --reasoning-parser qwen3 \
    --speculative-config "${SPEC}" \
    > "${ROOT}/logs/vllm-ornith-mtp1.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
ready=0
for i in $(seq 1 900); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "READY ornith-mtp1 after $((i * 2))s"
    ready=1
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED ornith-mtp1"
    tail -30 "${ROOT}/logs/vllm-ornith-mtp1.log" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
  if (( i % 20 == 0 )); then echo "waiting ornith-mtp1 ${i}"; tail -1 "${ROOT}/logs/vllm-ornith-mtp1.log" || true; fi
  sleep 2
done
if [[ "${ready}" != 1 ]]; then
  echo "TIMEOUT ornith" | tee -a "${ROOT}/failures.md"
  exit 1
fi
grep -E "KV cache size|Model loading took|Maximum concurrency" "${ROOT}/logs/vllm-ornith-mtp1.log" | tee "${ROOT}/raw/ornith-mtp1-kv.txt" || true
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --model "${MODEL}" \
  --hf-id "${MODEL}" \
  --quantization NVFP4 \
  --engine vllm \
  --engine-version "vllm 0.28.0 cuda-graphs mtp1" \
  --profiles A,B \
  --concurrencies 1,8,12 \
  --mode sustained \
  --duration 60 \
  --warmup 1 \
  --timeout 1800 \
  --tag ornith-mtp1-r2 \
  --context-configured 131072 \
  --kv-cache fp8 \
  --attention flashinfer \
  --moe-backend marlin \
  --mtp mtp \
  --draft-tokens 1 \
  --thinking off \
  --raw-dir "${ROOT}/raw"
kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
echo "ORNITH MTP DONE $(date -Is)"
