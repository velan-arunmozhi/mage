#!/bin/bash
# Qwen3.6 NVFP4 MTP3 at the native 262144 context. Thinking stays off.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/29-qwen-262.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/state"
exec > >(tee -a "${LOG}") 2>&1
echo "QWEN262 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
  mkdir -p "${QWEN_LOCAL}"
  cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
fi
python3 - <<'PY'
n = 40 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
ready=0
for attempt in 1 2; do
python3 - <<'PY'
n = 40 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
echo "CUDA_FREE ${FREE} ${TOTAL} attempt ${attempt}"
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.50, (free / total) - 0.02):.2f}")')
echo "UTIL ${UTIL}"
if [[ -f "${ROOT}/state/vllm-qwen262.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm-qwen262.pid")" 2>/dev/null || true; fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
sleep 8
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
    --served-model-name nvidia/Qwen3.6-35B-A3B-NVFP4 \
    --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len 262144 --max-num-seqs 2 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
    --attention-backend flashinfer --moe-backend marlin \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager --reasoning-parser qwen3 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
    > "${ROOT}/logs/vllm-qwen262.log" 2>&1 &
echo $! > "${ROOT}/state/vllm-qwen262.pid"
for i in $(seq 1 800); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "READY qwen262 $(hostname)"
    grep -E "KV cache size|CUDA graph|consumed memory|max_model_len|maximum context" "${ROOT}/logs/vllm-qwen262.log" | tee "${ROOT}/raw/qwen262-kv.txt" || true
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm-qwen262.pid")" 2>/dev/null; then
    echo "DIED qwen262 attempt ${attempt}"
    grep -E "Error|ValueError|illegal|Free memory|Available KV|max_model" "${ROOT}/logs/vllm-qwen262.log" | tail -20
    break
  fi
  sleep 2
done
if curl -sf http://127.0.0.1:8000/health >/dev/null; then ready=1; break; fi
done
if [[ "${ready}" != 1 ]]; then
  echo "QWEN262 FAILED"
  exit 1
fi
while [[ ! -f "${ROOT}/state/qwen262.stop" ]]; do
  sleep 15
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "QWEN262 HEALTH LOST $(date -Is)"
    exit 1
  fi
done
kill -9 "$(cat "${ROOT}/state/vllm-qwen262.pid")" 2>/dev/null || true
echo "QWEN262 STOP $(date -Is)"
