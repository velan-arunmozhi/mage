#!/bin/bash
# Reproduce GPT-OSS tool-name leaks, then test cutting <|channel|> out of the recipient.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
GPT_LOCAL=/tmp/models/gpt-oss-20b
PATCH="${ROOT}/patches/harmony_028_normalize_recipient.py"
LOG="${ROOT}/logs/28-gptoss-toolfix.out"
PIDF="${ROOT}/state/vllm-toolfix.pid"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/state" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "TOOLFIX2 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then echo "GPT weights missing"; exit 1; fi
  mkdir -p "${GPT_LOCAL}"
  cp -aL "${snap}/." "${GPT_LOCAL}/"
fi

stop_vllm() {
  if [[ -f "${PIDF}" ]]; then kill -9 "$(cat "${PIDF}")" 2>/dev/null || true; rm -f "${PIDF}"; fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do kill -9 "${pid}" 2>/dev/null || true; done
  sleep 12
}

module_path() {
  apptainer exec "${IMG}" python3 -c 'import vllm.parser.harmony as h; print(h.__file__)' 2>/dev/null | awk '/^\/.+harmony\.py$/ {print}'
}

launch() {
  local name="$1"
  local patch="$2"
  stop_vllm
  python3 - <<'PY'
n = 40 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
  read -r FREE TOTAL < <(apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))')
  local util
  util=$(python3 -c 'free=int("'"${FREE}"'"); total=int("'"${TOTAL}"'"); print(f"{min(0.45, (free / total) - 0.02):.2f}")')
  echo "CUDA_FREE ${FREE} UTIL ${util}"
  local bind=()
  if [[ -n "${patch}" ]]; then
    local target
    target=$(module_path)
    echo "BIND ${patch} -> ${target}"
    if [[ -z "${target}" ]]; then echo "NO_MODULE_PATH"; return 1; fi
    bind=(--bind "${patch}:${target}:ro")
  fi
  apptainer exec --nv "${bind[@]}" \
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
      --max-model-len 131072 --max-num-seqs 4 --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager \
      --tool-call-parser openai --enable-auto-tool-choice \
      > "${ROOT}/logs/vllm-toolfix-${name}.log" 2>&1 &
  echo $! > "${PIDF}"
  local i
  for i in $(seq 1 700); do
    if curl -sf http://127.0.0.1:8000/health >/dev/null; then
      echo "READY ${name}"
      return 0
    fi
    if ! kill -0 "$(cat "${PIDF}")" 2>/dev/null; then
      echo "DIED ${name}"
      tail -20 "${ROOT}/logs/vllm-toolfix-${name}.log"
      return 1
    fi
    sleep 2
  done
  return 1
}

echo "RENDER stock"
apptainer exec --nv \
  --bind "${ROOT}/encodings:/encodings:ro" \
  --env TIKTOKEN_ENCODINGS_BASE=/encodings \
  "${IMG}" python3 - <<'PY' | tee "${ROOT}/raw/harmony-render-stock.txt"
from vllm.entrypoints.openai.parser.harmony_utils import (
    get_encoding, parse_chat_inputs_to_harmony_messages, render_for_completion,
)
messages = [
    {"role": "user", "content": "City: Paris"},
    {"role": "assistant", "content": None, "tool_calls": [{"id": "call-0", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}}]},
    {"role": "tool", "tool_call_id": "call-0", "content": "{\"weather\": \"clear\"}"},
    {"role": "user", "content": "City: Lyon"},
]
print(get_encoding().decode(render_for_completion(parse_chat_inputs_to_harmony_messages(messages))))
PY

if launch stock ""; then
  python3 "${ROOT}/scripts/gptoss_tool_loop.py" http://127.0.0.1:8000 12 "${ROOT}/raw/toolloop-stock-auto.json"
else
  echo "STOCK_LAUNCH_FAILED"
  exit 1
fi

if python3 -c 'import json; d=json.load(open("'"${ROOT}"'/raw/toolloop-stock-auto.json")); raise SystemExit(0 if d["leaked"]==0 and d["errors"]==0 and d["clean"]==d["turns"] else 1)'; then
  echo "STOCK_ALREADY_CLEAN"
  touch "${ROOT}/state/gptoss-tool.fixed"
else
  if launch patched "${PATCH}"; then
    python3 "${ROOT}/scripts/gptoss_tool_loop.py" http://127.0.0.1:8000 12 "${ROOT}/raw/toolloop-patched-auto.json"
    if python3 -c 'import json; d=json.load(open("'"${ROOT}"'/raw/toolloop-patched-auto.json")); raise SystemExit(0 if d["leaked"]==0 and d["errors"]==0 and d["turns"]>=10 else 1)'; then
      echo "FIXED recipient-normalize"
      touch "${ROOT}/state/gptoss-tool.fixed"
    else
      echo "NOT_FIXED recipient-normalize"
    fi
  else
    echo "PATCH_LAUNCH_FAILED"
  fi
fi
echo "TOOLFIX2 TESTS DONE $(date -Is)"
while [[ ! -f "${ROOT}/state/gptoss-tool.stop" ]]; do
  sleep 15
  if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "GPT HEALTH LOST $(date -Is)"
    exit 1
  fi
done
stop_vllm
echo "TOOLFIX2 STOP $(date -Is)"
