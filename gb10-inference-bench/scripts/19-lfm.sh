#!/bin/bash
# One LFM2.5-24B-A2B FP8 start below the measured free-memory gate.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
LFM_MODEL="LiquidAI/LFM2.5-24B-A2B-FP8"
LFM_LOCAL=/tmp/models/lfm25-fp8
LOG="${ROOT}/logs/19-lfm.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "LFMJOB START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${LFM_LOCAL}/config.json" ]]; then
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind /tmp/models:/tmp/models \
    --env HF_HOME=/root/.cache/huggingface \
    --env PYTHONUNBUFFERED=1 \
    "${IMG}" python3 - <<PY
from huggingface_hub import snapshot_download
print("LFM_DOWNLOAD", snapshot_download("${LFM_MODEL}", local_dir="${LFM_LOCAL}"))
PY
fi
read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(f,t)')
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.40, (free / total) * 0.75):.2f}")')
echo "CUDA_FREE ${FREE} TOTAL ${TOTAL} UTIL ${UTIL}"
stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 6
}
launch() {
  local seqs="$1"
  stop_server
  echo "LAUNCH lfm seqs=${seqs} util=${UTIL}"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --bind /tmp/models:/tmp/models \
    --env HF_HOME=/root/.cache/huggingface \
    --env PYTHONUNBUFFERED=1 \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
    "${IMG}" vllm serve "${LFM_LOCAL}" \
      --served-model-name "${LFM_MODEL}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager \
      > "${ROOT}/logs/vllm-lfm-s${seqs}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 700); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY lfm seqs=${seqs}"
      grep -E "KV cache size|Available KV|consumed memory|Model loading took" "${ROOT}/logs/vllm-lfm-s${seqs}.log" | tee "${ROOT}/raw/lfm-s${seqs}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED lfm seqs=${seqs}"
      grep -E "ValueError|illegal|Error|not support|Free memory" "${ROOT}/logs/vllm-lfm-s${seqs}.log" | tail -12 | tee "${ROOT}/raw/lfm-s${seqs}-error.txt"
      return 1
    fi
    sleep 2
  done
  return 1
}
SEQS=16
if ! launch 16; then
  echo "16 sequences failed; one retry at 4"
  if ! launch 4; then
    echo "LFM_BLOCKED"
    stop_server
    echo "LFMJOB DONE $(date -Is)"
    exit 0
  fi
  SEQS=4
fi
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --model "${LFM_MODEL}" --hf-id "${LFM_MODEL}" \
  --quantization FP8 --engine vllm --engine-version 0.28.0 \
  --profiles A --concurrencies 1,8,16 --mode sustained --duration 60 --warmup 1 \
  --tag "lfm25-fp8-s${SEQS}" --context-configured 131072 --kv-cache fp8 \
  --attention auto --moe-backend auto --mtp off --draft-tokens 0 --thinking off \
  || echo "lfm A failed"
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --model "${LFM_MODEL}" --hf-id "${LFM_MODEL}" \
  --quantization FP8 --engine vllm --engine-version 0.28.0 \
  --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
  --tag "lfm25-fp8-s${SEQS}" --context-configured 131072 --kv-cache fp8 \
  --attention auto --moe-backend auto --mtp off --draft-tokens 0 --thinking off \
  || echo "lfm B failed"
A16=$(grep "RESULT lfm25-fp8-s${SEQS}-A-c16" "${LOG}" | tail -1 | sed -n 's/.*agg=\([0-9.]*\).*/\1/p')
echo "LFM_A16 ${A16}"
awk -v a="${A16:-0}" 'BEGIN{exit !(a+0 >= 400)}' && {
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${LFM_MODEL}" \
    --mtp "lfm25-fp8-s${SEQS}" --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
    --min-tokens 1024 --max-tokens 1024 || echo "lfm long failed"
  python3 "${ROOT}/scripts/quality_hard.py" --model "${LFM_MODEL}" --tag lfm25-fp8 --thinking off --engine vllm --max-tokens 4096 \
    || echo "lfm quality failed"
} || echo "LFM below 400 tok/s at 16 clients; no long-context or quality run"
stop_server
echo "LFMJOB DONE $(date -Is)"
