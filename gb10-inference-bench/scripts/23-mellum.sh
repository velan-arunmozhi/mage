#!/bin/bash
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MID="JetBrains/Mellum2.1-12B-A2.5B-Thinking"
LOCAL=/tmp/models/mellum21
LOG="${ROOT}/logs/23-mellum.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "MELLUMJOB START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--JetBrains--Mellum2.1-12B-A2.5B-Thinking/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then echo "MELLUM_MISSING"; exit 1; fi
  mkdir -p "${LOCAL}"
  cp -aL "${snap}/." "${LOCAL}/"
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
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); room=(free/total)*0.80; print(f"{min(0.42, room):.2f}")')
echo "CUDA_FREE ${FREE} TOTAL ${TOTAL} UTIL ${UTIL}"
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
echo "LAUNCH mellum util=${UTIL} seqs=32"
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
  --bind "${ROOT}/tmp:/tmp" \
  --bind /tmp/models:/tmp/models \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  --env VLLM_CACHE_ROOT=/root/.cache/vllm \
  --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
  "${IMG}" vllm serve "${LOCAL}" \
    --served-model-name "${MID}" \
    --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len 131072 --max-num-seqs 32 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization "${UTIL}" \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager \
    --reasoning-parser qwen3 \
    > "${ROOT}/logs/vllm-mellum-final.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
for i in $(seq 1 700); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then echo "READY mellum"; break; fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED mellum"
    grep -E "Error|ValueError|illegal|Free memory" "${ROOT}/logs/vllm-mellum-final.log" | tail -10
    exit 1
  fi
  sleep 2
done
grep -E "KV cache size|Available KV|consumed memory|Model loading" "${ROOT}/logs/vllm-mellum-final.log" | tee "${ROOT}/raw/mellum-final-kv.txt" || true
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${MID}" --hf-id "${MID}" \
  --quantization BF16 --engine vllm --engine-version 0.28.0 \
  --profiles A --concurrencies 1,8,16,32 --mode sustained --duration 60 --warmup 1 \
  --tag mellum21-think --context-configured 131072 --kv-cache bf16 \
  --attention auto --moe-backend auto --mtp off --draft-tokens 0 \
  --thinking server-default || echo "A failed"
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${MID}" --hf-id "${MID}" \
  --quantization BF16 --engine vllm --engine-version 0.28.0 \
  --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
  --tag mellum21-think --context-configured 131072 --kv-cache bf16 \
  --attention auto --moe-backend auto --mtp off --draft-tokens 0 \
  --thinking server-default || echo "B failed"
python3 "${ROOT}/scripts/long_concurrency.py" --model "${MID}" \
  --mtp mellum21-think --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
  --min-tokens 256 --max-tokens 256 || echo "long failed"
python3 "${ROOT}/scripts/quality_hard.py" --model "${MID}" --tag mellum21-think --thinking server-default --engine vllm --max-tokens 4096 \
  || echo "quality failed"
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
echo "MELLUMJOB DONE $(date -Is)"
