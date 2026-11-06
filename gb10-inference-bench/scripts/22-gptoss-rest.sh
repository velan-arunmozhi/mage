#!/bin/bash
# Finish GPT-OSS profile B, the 118k check, and medium-effort quality on the working 64-sequence server.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
GPT_ID="openai/gpt-oss-20b"
GPT_LOCAL=/tmp/models/gpt-oss-20b
LOG="${ROOT}/logs/22-gptoss-rest.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "GPTOSS REST START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then echo "GPT weights missing"; exit 1; fi
  mkdir -p "${GPT_LOCAL}"
  echo "COPY gpt-oss from ${snap}"
  cp -aL "${snap}/." "${GPT_LOCAL}/"
fi
python3 - <<'PY'
n = 60 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.45, (free / total) * 0.65):.2f}")')
echo "CUDA_FREE ${FREE} TOTAL ${TOTAL} UTIL ${UTIL}"
stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; rm -f "${ROOT}/state/vllm.pid"; fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
  sleep 8
}
launch() {
  local name="$1" seqs="$2"
  stop_all
  # Let file cache settle so the profiler's free-memory snapshot does not rise mid-init.
  sleep 5
  echo "LAUNCH ${name} seqs=${seqs} util=${UTIL}"
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
      --served-model-name "${GPT_ID}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager \
      --tool-call-parser openai --enable-auto-tool-choice \
      > "${ROOT}/logs/vllm-gptoss-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 700); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name}"
      grep -E "KV cache size|Available KV|consumed memory" "${ROOT}/logs/vllm-gptoss-${name}.log" | tee "${ROOT}/raw/gptoss-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "Error|ValueError|illegal|Free memory|AssertionError" "${ROOT}/logs/vllm-gptoss-${name}.log" | tail -8
      return 1
    fi
    sleep 2
  done
  return 1
}
if ! launch s64 64; then
  echo "GPT_RELAUNCH_FAILED"
  exit 1
fi
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
  --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
  --profiles B --concurrencies 1,8,16,32 --mode sustained --duration 60 --warmup 1 \
  --tag gptoss-low --context-configured 131072 --kv-cache fp8 \
  --attention flashinfer --moe-backend default --mtp off --draft-tokens 0 \
  --thinking low || echo "B failed"
python3 "${ROOT}/scripts/long_concurrency.py" --model "${GPT_ID}" \
  --mtp gptoss-low --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
  --min-tokens 1024 --max-tokens 1024 --system "Reasoning: low" || echo "long failed"
python3 "${ROOT}/scripts/quality_hard.py" --model "${GPT_ID}" --tag gptoss-medium --thinking medium --engine vllm --max-tokens 4096 \
  || echo "quality failed"
echo "one attempt at 128 sequences after the required measurements"
if launch s128 128; then
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
    --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
    --profiles A --concurrencies 96,128 --mode sustained --duration 60 --warmup 1 \
    --tag gptoss-low --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend default --mtp off --draft-tokens 0 \
    --thinking low || echo "A extend failed"
fi
echo "GPTOSS REST DONE $(date -Is)"
stop_all
