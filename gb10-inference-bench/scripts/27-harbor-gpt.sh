#!/bin/bash
# GPT-OSS-20B for the Harbor agent. Reasoning effort is set by the local proxy.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
GPT_LOCAL=/tmp/models/gpt-oss-20b
LOG="${ROOT}/logs/27-harbor-gpt.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/state"
exec > >(tee -a "${LOG}") 2>&1
echo "HARBOR-GPT START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then echo "GPT weights missing"; exit 1; fi
  mkdir -p "${GPT_LOCAL}"
  cp -aL "${snap}/." "${GPT_LOCAL}/"
fi
python3 - <<'PY'
n = 50 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
echo "CUDA_FREE ${FREE} ${TOTAL}"
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.45, (free / total) - 0.02):.2f}")')
echo "UTIL ${UTIL}"
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
sleep 3
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
  --bind "${ROOT}/tmp:/tmp" \
  --bind /tmp/models:/tmp/models \
  --bind "${ROOT}/encodings:/encodings:ro" \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  --env VLLM_CACHE_ROOT=/root/.cache/vllm \
  --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
  --env TIKTOKEN_ENCODINGS_BASE=/encodings \
  "${IMG}" vllm serve "${GPT_LOCAL}" \
    --served-model-name gpt-oss-20b \
    --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager \
    --tool-call-parser openai --enable-auto-tool-choice \
    > "${ROOT}/logs/vllm-harbor-gpt.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
for i in $(seq 1 800); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "READY gpt $(hostname)"
    grep -E "KV cache size|consumed memory" "${ROOT}/logs/vllm-harbor-gpt.log" | tee "${ROOT}/raw/harbor-gpt-kv.txt" || true
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED gpt"
    grep -E "Error|ValueError|illegal|Free memory|Harmony" "${ROOT}/logs/vllm-harbor-gpt.log" | tail -12
    exit 1
  fi
  sleep 2
done
while [[ ! -f "${ROOT}/state/harbor-gpt.stop" ]]; do
  sleep 15
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "GPT HEALTH LOST $(date -Is)"
    exit 1
  fi
done
kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
echo "HARBOR-GPT STOP $(date -Is)"
