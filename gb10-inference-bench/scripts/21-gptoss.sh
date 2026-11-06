#!/bin/bash
# GPT-OSS-20B after the Harmony vocab files are available locally.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
GPT_ID="openai/gpt-oss-20b"
GPT_LOCAL=/tmp/models/gpt-oss-20b
LOG="${ROOT}/logs/21-gptoss.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "GPTOSS START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then
    echo "GPT weights missing"
    exit 1
  fi
  mkdir -p "${GPT_LOCAL}"
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
UTIL=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.55, (free / total) * 0.70):.2f}")')
echo "CUDA_FREE ${FREE} TOTAL ${TOTAL} UTIL ${UTIL}"
if ! awk -v u="${UTIL}" 'BEGIN{exit !(u+0 >= 0.25)}'; then
  echo "UTIL too low"
  exit 1
fi
stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true; rm -f "${ROOT}/state/vllm.pid"; fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
  sleep 6
}
launch() {
  local name="$1" seqs="$2"
  stop_all
  echo "LAUNCH ${name} seqs=${seqs} util=${UTIL}"
  printf '%s\n' "vllm serve ${GPT_LOCAL} max-model-len 131072 max-num-seqs ${seqs} util ${UTIL} kv fp8 attention flashinfer tool-parser openai TIKTOKEN_ENCODINGS_BASE=/encodings" > "${ROOT}/configs/gptoss-${name}.cmd"
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
      grep -E "KV cache size|Available KV|consumed memory|Model loading took" "${ROOT}/logs/vllm-gptoss-${name}.log" | tee "${ROOT}/raw/gptoss-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "Error|ValueError|illegal|Free memory" "${ROOT}/logs/vllm-gptoss-${name}.log" | tail -12
      return 1
    fi
    sleep 2
  done
  return 1
}
if ! launch s64 64; then
  echo "GPT_LAUNCH_FAILED"
  exit 1
fi
python3 - <<PY
import json, urllib.request
def post(body):
    req=urllib.request.Request("http://127.0.0.1:${PORT}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())
low=post({"model":"${GPT_ID}","messages":[{"role":"system","content":"Reasoning: low"},{"role":"user","content":"What is 17+4? Reply with the integer only."}],"max_tokens":128,"temperature":0})
msg=(low.get("choices") or [{}])[0].get("message") or {}
print("REASONING_SMOKE", json.dumps({"content": msg.get("content"), "reasoning": msg.get("reasoning") or msg.get("reasoning_content"), "usage": low.get("usage")})[:1500])
tool=post({"model":"${GPT_ID}","messages":[{"role":"system","content":"Reasoning: low"},{"role":"user","content":"Use get_weather for Paris."}],"tools":[{"type":"function","function":{"name":"get_weather","description":"Weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],"tool_choice":"auto","max_tokens":256,"temperature":0})
tmsg=(tool.get("choices") or [{}])[0].get("message") or {}
print("TOOL_SMOKE", json.dumps({"tool_calls": tmsg.get("tool_calls"), "content": (tmsg.get("content") or "")[:400]})[:1500])
PY
bench() {
  local profile="$1" concs="$2" tag="$3"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
    --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
    --profiles "${profile}" --concurrencies "${concs}" --mode sustained --duration 60 --warmup 1 \
    --tag "${tag}" --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend default --mtp off --draft-tokens 0 \
    --thinking low || echo "bench ${profile} ${concs} failed"
}
bench A 1,8,16,32,64 gptoss-low
NEXT=$(python3 - <<'PY'
import json
rows=[]
for line in open("/scratch/scholar/billin19/gb10-inference-bench/results.jsonl"):
    row=json.loads(line)
    if row.get("experiment_id","").startswith("gptoss-low-A-c") and row.get("status")=="ok":
        rows.append(row)
rows.sort(key=lambda r: r.get("concurrency_requested") or 0)
if len(rows)<2:
    print("stop"); raise SystemExit
last, prev = rows[-1], rows[-2]
running=float(last.get("engine_running_max") or 0)
req=float(last.get("concurrency_requested") or 1)
agg=float(last.get("aggregate_tok_s") or 0)
prev_agg=float(prev.get("aggregate_tok_s") or 0)
print("extend" if agg>prev_agg*1.05 and running>=req*0.9 else "stop")
print(f"last c={req} agg={agg} run={running}")
PY
)
echo "GPT_A_DECISION ${NEXT}"
if [[ "${NEXT}" == extend* ]]; then
  if launch s128 128; then
    bench A 96,128 gptoss-low
  fi
fi
if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  bench B 1,8,16,32 gptoss-low
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${GPT_ID}" \
    --mtp gptoss-low --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
    --min-tokens 1024 --max-tokens 1024 --system "Reasoning: low" || echo "long failed"
  python3 "${ROOT}/scripts/quality_hard.py" --model "${GPT_ID}" --tag gptoss-medium --thinking medium --engine vllm --max-tokens 4096 \
    || echo "quality medium failed"
fi
stop_all
echo "GPTOSS DONE $(date -Is)"
