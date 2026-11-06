#!/bin/bash
# MTP3 long-context decode with max-num-seqs 4 and utilization 0.45, matching the MTP0 run.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/15-long-fair.out"
mkdir -p /tmp/vllm-apptainer /tmp/models
exec > >(tee -a "${LOG}") 2>&1
echo "LONGFAIR START $(date -Is) $(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
  mkdir -p "${QWEN_LOCAL}"
  cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "$pid" 2>/dev/null || true; done
SPEC='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
echo "LAUNCH mtp3 seqs=4 util=0.45 $(date -Is)"
free -h
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
    --max-model-len 131072 --max-num-seqs 4 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.45 --kv-cache-dtype fp8 \
    --attention-backend flashinfer --moe-backend marlin \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager --reasoning-parser qwen3 \
    --speculative-config "${SPEC}" \
    > "${ROOT}/logs/vllm-mtp3-longfair.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
for i in $(seq 1 900); do
  if curl -sf http://127.0.0.1:${PORT}/health >/dev/null; then echo "READY after $((i*2))s"; break; fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED"; tail -30 "${ROOT}/logs/vllm-mtp3-longfair.log"; exit 1
  fi
  sleep 2
done
grep -E "KV cache size|Model loading took" "${ROOT}/logs/vllm-mtp3-longfair.log" | tee "${ROOT}/raw/mtp3-longfair-kv.txt"
python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp3-fair --draft-tokens 3 --concurrency 1 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024
python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp3-fair --draft-tokens 3 --concurrency 4 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024
kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "$pid" 2>/dev/null || true; done
echo "LONGFAIR DONE $(date -Is)"
