#!/bin/bash
# Frozen Qwen3.6 NVFP4 MTP3 server for Harbor. Thinking is forced off.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"

# Optimal setup, pinned. Utilization is measured at launch, not pinned.
MODEL_HF="nvidia/Qwen3.6-35B-A3B-NVFP4"
MODEL_REVISION="1355db6a052410cfd62085d94b58866fd0f2c3c5"
VLLM_VERSION="0.28.0"
CONTEXT=131072
MAX_SEQS=4
MAX_BATCHED_TOKENS=8192

IMG=/tmp/vllm-apptainer/vllm-openai-${VLLM_VERSION}.sif
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/${MODEL_REVISION}"
if [[ "${VLLM_SIF}" != *"vllm-openai-${VLLM_VERSION}.sif" ]]; then
  echo "Refusing VLLM_SIF=${VLLM_SIF}; this server is pinned to vLLM ${VLLM_VERSION}." >&2
  exit 2
fi
if [[ ! -f "${SNAP}/config.json" ]]; then
  echo "Pinned snapshot ${MODEL_REVISION} is missing." >&2
  exit 2
fi
LOG="${ROOT}/logs/26-harbor-qwen.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/state"
exec > >(tee -a "${LOG}") 2>&1
echo "HARBOR-QWEN START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
echo "PIN model=${MODEL_HF} revision=${MODEL_REVISION} vllm=${VLLM_VERSION} context=${CONTEXT} seqs=${MAX_SEQS} mtp=3 moe=marlin draft=triton attn=flashinfer kv=fp8 thinking=off graphs=on"
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
read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
echo "CUDA_FREE ${FREE} ${TOTAL}"
# MTP3 often profiles ~22 GiB, and sometimes ~50 GiB. Stay just under the free-memory gate.
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.44, (free / total) - 0.02):.2f}")')
echo "UTIL ${UTIL}"
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
sleep 3
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
    --served-model-name "${MODEL_HF}" \
    --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len "${CONTEXT}" --max-num-seqs "${MAX_SEQS}" --max-num-batched-tokens "${MAX_BATCHED_TOKENS}" \
    --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
    --attention-backend flashinfer --moe-backend marlin \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager --reasoning-parser qwen3 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
    > "${ROOT}/logs/vllm-harbor-qwen.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
for i in $(seq 1 800); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "READY qwen $(hostname)"
    grep -E "KV cache size|CUDA graph pool|consumed memory" "${ROOT}/logs/vllm-harbor-qwen.log" | tee "${ROOT}/raw/harbor-qwen-kv.txt" || true
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED qwen"
    grep -E "Error|ValueError|illegal|Free memory" "${ROOT}/logs/vllm-harbor-qwen.log" | tail -12
    exit 1
  fi
  sleep 2
done
# Stay up for the Harbor run. Stop when state/harbor-qwen.stop appears.
while [[ ! -f "${ROOT}/state/harbor-qwen.stop" ]]; do
  sleep 15
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "QWEN HEALTH LOST $(date -Is)"
    exit 1
  fi
done
kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
echo "HARBOR-QWEN STOP $(date -Is)"
