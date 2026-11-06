#!/bin/bash
# Warm 8k scaling for GPT-OSS: reproduce 64, diagnose 48, then 80 and maybe 96.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
GPT_ID="openai/gpt-oss-20b"
GPT_LOCAL=/tmp/models/gpt-oss-20b
LOG="${ROOT}/logs/25-gptoss-bscale.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "BSCALE START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  [[ -n "${snap}" && -f "${snap}/config.json" ]] || { echo "weights missing"; exit 1; }
  mkdir -p "${GPT_LOCAL}"
  cp -aL "${snap}/." "${GPT_LOCAL}/"
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
sleep 5
read -r FREE2 TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
echo "FREE ${FREE} then ${FREE2} total ${TOTAL}"
UTIL=$(python3 -c 'free=int("'"${FREE2}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.42, (free / total) * 0.65):.2f}")')
echo "UTIL ${UTIL}"
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
echo "LAUNCH bscale seqs=96 util=${UTIL}"
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
    --max-model-len 131072 --max-num-seqs 96 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
    --attention-backend flashinfer \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager \
    --tool-call-parser openai --enable-auto-tool-choice \
    > "${ROOT}/logs/vllm-bscale.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
for i in $(seq 1 700); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then echo "READY bscale"; break; fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED bscale"
    grep -E "AssertionError|ValueError|illegal|Free memory" "${ROOT}/logs/vllm-bscale.log" | tail -8
    exit 1
  fi
  sleep 2
done
grep -E "KV cache size|CUDA graph pool|consumed memory|Free memory on device" "${ROOT}/logs/vllm-bscale.log" | tee "${ROOT}/raw/bscale-kv.txt"
# One full 8k prefill so the timed 64-client run is not the first long batch.
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
  --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
  --profiles B --concurrencies 1 --mode sustained --duration 20 --warmup 1 \
  --tag gptoss-bscale-warmup --context-configured 131072 --kv-cache fp8 \
  --attention flashinfer --moe-backend default --mtp off --thinking low || true
python3 "${ROOT}/scripts/bench_client.py" \
  --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
  --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
  --profiles B --concurrencies 64,48,80 --mode sustained --duration 60 --warmup 1 \
  --tag gptoss-bscale --context-configured 131072 --kv-cache fp8 \
  --attention flashinfer --moe-backend default --mtp off --thinking low || echo "bench 64-80 failed"
UP=$(python3 - <<'PY'
import json
rows={}
for line in open("/scratch/scholar/billin19/gb10-inference-bench/results.jsonl"):
    r=json.loads(line)
    eid=r.get("experiment_id","")
    if eid.startswith("gptoss-bscale-B-c") and "warmup" not in eid:
        rows[int(r.get("concurrency_requested") or 0)]=r
a=rows.get(64); b=rows.get(80)
if not a or not b:
    print("no"); raise SystemExit
run=float(b.get("engine_running_max") or 0)
agg=float(b.get("aggregate_tok_s") or 0)
prev=float(a.get("aggregate_tok_s") or 0)
ttft=float(b.get("ttft_p50_s") or 99)
print("yes" if agg>prev*1.05 and run>=72 and ttft<20 else "no")
print(f"64={prev:.1f} 80={agg:.1f} run={run:.0f} ttft={ttft:.2f}")
PY
)
echo "B80_DECISION ${UP}"
if [[ "${UP}" == yes* ]]; then
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
    --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
    --profiles B --concurrencies 96 --mode sustained --duration 60 --warmup 1 \
    --tag gptoss-bscale --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend default --mtp off --thinking low || echo "bench 96 failed"
fi
if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; fi
echo "BSCALE DONE $(date -Is)"
