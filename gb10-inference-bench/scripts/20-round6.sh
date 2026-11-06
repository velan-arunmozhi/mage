#!/bin/bash
# GPT-OSS-20B MXFP4, then Mellum2.1 BF16 if the allocation remains.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
LOG="${ROOT}/logs/20-round6.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "ROUND6 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"

stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  if [[ -f "${ROOT}/state/llama.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/llama.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/llama.pid"
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 8
}

util_now() {
  # CUDA free memory ignores reclaimable file cache. Touch a large anonymous
  # buffer so the kernel drops that cache before vLLM's startup check.
  python3 - <<'PY'
n = 60 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED 60GiB file cache")
PY
  free -h | head -2
  apptainer exec --nv "${IMG}" python3 - <<'PY'
import torch
free, total = torch.cuda.mem_get_info()
util = min(0.60, (free / total) * 0.85)
print(f"CUDA_FREE {free} {total} UTIL {util:.2f}")
print(f"{util:.2f}")
PY
}

materialize() {
  local repo="$1" dest="$2" cache_name="$3"
  if [[ -f "${dest}/config.json" ]]; then
    return 0
  fi
  if [[ -d "${dest}" ]]; then rm -rf "${dest}"; fi
  echo "DOWNLOAD ${repo}"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --env HF_HOME=/root/.cache/huggingface \
    --env PYTHONUNBUFFERED=1 \
    "${IMG}" python3 - <<PY
from huggingface_hub import snapshot_download
print("CACHE", snapshot_download("${repo}"))
PY
  local snap
  snap=$(find "${HF_HOME}/hub/${cache_name}/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then
    echo "SNAPSHOT_MISSING ${repo}"
    return 1
  fi
  mkdir -p "${dest}"
  cp -aL "${snap}/." "${dest}/"
  test -f "${dest}/config.json"
}

# name local seqs extra_args_string
launch_vllm() {
  local name="$1" model_path="$2" served="$3" seqs="$4" extra="$5"
  local util info
  stop_all
  info=$(util_now)
  echo "${info}"
  util=$(printf '%s\n' "${info}" | tail -1)
  if ! awk -v u="${util:-0}" 'BEGIN{exit !(u+0 >= 0.25)}'; then
    echo "UTIL ${util} is below 0.25; not launching ${name}"
    return 1
  fi
  echo "LAUNCH ${name} seqs=${seqs} util=${util} extra=${extra}"
  printf '%s\n' "name=${name} seqs=${seqs} util=${util} ${extra}" > "${ROOT}/configs/round6-${name}.cmd"
  # shellcheck disable=SC2086
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --bind /tmp/models:/tmp/models \
    --env HF_HOME=/root/.cache/huggingface \
    --env PYTHONUNBUFFERED=1 \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
    "${IMG}" vllm serve "${model_path}" \
      --served-model-name "${served}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager \
      ${extra} \
      > "${ROOT}/logs/vllm-r6-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 800); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s util=${util}"
      grep -E "KV cache size|Available KV|consumed memory|Model loading took|moe" "${ROOT}/logs/vllm-r6-${name}.log" | tee "${ROOT}/raw/r6-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "Error|ValueError|illegal|unrecognized|Free memory|not support" "${ROOT}/logs/vllm-r6-${name}.log" | tail -15 | tee "${ROOT}/raw/r6-${name}-error.txt"
      return 1
    fi
    if (( i % 30 == 0 )); then echo "waiting ${name} ${i}"; fi
    sleep 2
  done
  echo "TIMEOUT ${name}"
  return 1
}

if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
apptainer exec --nv "${IMG}" vllm --version

GPT_ID="openai/gpt-oss-20b"
GPT_LOCAL=/tmp/models/gpt-oss-20b
if ! materialize "${GPT_ID}" "${GPT_LOCAL}" "models--openai--gpt-oss-20b"; then
  echo "GPT-OSS download failed" | tee -a "${ROOT}/failures.md"
else
  python3 - <<PY
import json
from pathlib import Path
cfg=json.loads(Path("${GPT_LOCAL}/config.json").read_text())
print("GPT_CONFIG", json.dumps({k: cfg.get(k) for k in ("model_type","architectures","max_position_embeddings","quantization_config")}, default=str)[:2000])
PY
  # flashinfer_trtllm MXFP4+MXFP8 refused this SM121 device. Use vLLM's default MXFP4 path.
  GPT_EXTRA="--kv-cache-dtype fp8 --attention-backend flashinfer --tool-call-parser openai --enable-auto-tool-choice"
  if ! launch_vllm gpt-default "${GPT_LOCAL}" "${GPT_ID}" 64 "${GPT_EXTRA}"; then
    echo "retry GPT-OSS without an explicit attention backend"
    GPT_EXTRA="--kv-cache-dtype fp8"
    launch_vllm gpt-plain "${GPT_LOCAL}" "${GPT_ID}" 64 "${GPT_EXTRA}" || true
  fi
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    python3 - <<PY
import json, urllib.request
def post(body):
    req=urllib.request.Request("http://127.0.0.1:${PORT}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())
low=post({"model":"${GPT_ID}","messages":[{"role":"system","content":"Reasoning: low"},{"role":"user","content":"What is 17+4? Reply with the integer only."}],"max_tokens":128,"temperature":0})
msg=(low.get("choices") or [{}])[0].get("message") or {}
print("REASONING_SMOKE", json.dumps({"content": msg.get("content"), "reasoning": msg.get("reasoning") or msg.get("reasoning_content"), "usage": low.get("usage")})[:1500])
tool=post({
  "model":"${GPT_ID}",
  "messages":[{"role":"system","content":"Reasoning: low"},{"role":"user","content":"Use get_weather for Paris."}],
  "tools":[{"type":"function","function":{"name":"get_weather","description":"Weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
  "tool_choice":"auto","max_tokens":256,"temperature":0,
})
tmsg=(tool.get("choices") or [{}])[0].get("message") or {}
print("TOOL_SMOKE", json.dumps({"tool_calls": tmsg.get("tool_calls"), "content": (tmsg.get("content") or "")[:300]})[:1500])
PY
    python3 "${ROOT}/scripts/bench_client.py" \
      --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
      --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
      --profiles A --concurrencies 1,8,16,32,64 --mode sustained --duration 60 --warmup 1 \
      --tag gptoss-low --context-configured 131072 --kv-cache fp8 \
      --attention flashinfer --moe-backend flashinfer_trtllm --mtp off --draft-tokens 0 \
      --thinking low || echo "gpt A failed"
    NEXT=$(python3 - <<'PY'
import json
rows=[]
for line in open("/scratch/scholar/billin19/gb10-inference-bench/results.jsonl"):
    if "gptoss-low-A-c" in line and "sustained" in line:
        rows.append(json.loads(line))
rows.sort(key=lambda r: r.get("concurrency_requested") or 0)
if len(rows) < 2:
    print("stop"); raise SystemExit
last, prev = rows[-1], rows[-2]
running=float(last.get("engine_running_max") or 0)
req=float(last.get("concurrency_requested") or 1)
climbing=(last.get("aggregate_tok_s") or 0) > (prev.get("aggregate_tok_s") or 0) * 1.05 and running >= req * 0.9
print("extend" if climbing else "stop")
print("last", last.get("concurrency_requested"), last.get("aggregate_tok_s"), "run", running)
PY
)
    echo "GPT_A_DECISION ${NEXT}"
    if [[ "${NEXT}" == extend* ]]; then
      if launch_vllm gpt-s128 "${GPT_LOCAL}" "${GPT_ID}" 128 "${GPT_EXTRA}"; then
        python3 "${ROOT}/scripts/bench_client.py" \
          --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
          --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
          --profiles A --concurrencies 96,128 --mode sustained --duration 60 --warmup 1 \
          --tag gptoss-low --context-configured 131072 --kv-cache fp8 \
          --attention flashinfer --moe-backend flashinfer_trtllm --mtp off --draft-tokens 0 \
          --thinking low || echo "gpt A extend failed"
      fi
    fi
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      python3 "${ROOT}/scripts/bench_client.py" \
        --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
        --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
        --profiles B --concurrencies 1,8,16,32 --mode sustained --duration 60 --warmup 1 \
        --tag gptoss-low --context-configured 131072 --kv-cache fp8 \
        --attention flashinfer --moe-backend flashinfer_trtllm --mtp off --draft-tokens 0 \
        --thinking low || echo "gpt B failed"
      python3 "${ROOT}/scripts/long_concurrency.py" --model "${GPT_ID}" \
        --mtp gptoss-low --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
        --min-tokens 1024 --max-tokens 1024 --system "Reasoning: low" || echo "gpt long failed"
      python3 "${ROOT}/scripts/quality_hard.py" --model "${GPT_ID}" --tag gptoss-medium --thinking medium --engine vllm --max-tokens 4096 \
        || echo "gpt quality medium failed"
    fi
  fi
fi
stop_all

echo "MELLUM START $(date -Is)"
MELLUM_ID="JetBrains/Mellum2.1-12B-A2.5B-Thinking"
MELLUM_LOCAL=/tmp/models/mellum21
if materialize "${MELLUM_ID}" "${MELLUM_LOCAL}" "models--JetBrains--Mellum2.1-12B-A2.5B-Thinking"; then
  python3 - <<PY
import json
from pathlib import Path
cfg=json.loads(Path("${MELLUM_LOCAL}/config.json").read_text())
print("MELLUM_CONFIG", json.dumps({k: cfg.get(k) for k in ("model_type","architectures","max_position_embeddings","torch_dtype")}))
PY
  if ! launch_vllm mellum-bf16 "${MELLUM_LOCAL}" "${MELLUM_ID}" 32 "--kv-cache-dtype fp8 --reasoning-parser qwen3"; then
    echo "retry Mellum without FP8 KV"
    launch_vllm mellum-bf16-nokv "${MELLUM_LOCAL}" "${MELLUM_ID}" 32 "--reasoning-parser qwen3" || true
  fi
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    python3 "${ROOT}/scripts/bench_client.py" \
      --base-url "http://127.0.0.1:${PORT}" --model "${MELLUM_ID}" --hf-id "${MELLUM_ID}" \
      --quantization BF16 --engine vllm --engine-version 0.28.0 \
      --profiles A --concurrencies 1,8,16,32 --mode sustained --duration 60 --warmup 1 \
      --tag mellum21-think --context-configured 131072 --kv-cache fp8 \
      --attention auto --moe-backend auto --mtp off --draft-tokens 0 \
      --thinking server-default || echo "mellum A failed"
    python3 "${ROOT}/scripts/bench_client.py" \
      --base-url "http://127.0.0.1:${PORT}" --model "${MELLUM_ID}" --hf-id "${MELLUM_ID}" \
      --quantization BF16 --engine vllm --engine-version 0.28.0 \
      --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
      --tag mellum21-think --context-configured 131072 --kv-cache fp8 \
      --attention auto --moe-backend auto --mtp off --draft-tokens 0 \
      --thinking server-default || echo "mellum B failed"
    python3 "${ROOT}/scripts/long_concurrency.py" --model "${MELLUM_ID}" \
      --mtp mellum21-think --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
        --min-tokens 1024 --max-tokens 1024 || echo "mellum long failed"
    python3 "${ROOT}/scripts/quality_hard.py" --model "${MELLUM_ID}" --tag mellum21-think --thinking server-default --engine vllm --max-tokens 4096 \
      || echo "mellum quality failed"
  else
    echo "MELLUM_VLLM_FAILED"
  fi
else
  echo "MELLUM_DOWNLOAD_FAILED"
fi
stop_all
echo "ROUND6 DONE $(date -Is)"
