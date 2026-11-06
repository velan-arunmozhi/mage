#!/bin/bash
# NVFP4 already loaded once from /tmp/models/qwen36-nvfp4 (20.4 GiB, 621k KV tokens
# at gpu-memory-utilization 0.40). Restart with a 131072 context and a long readiness wait.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
LOCAL=/tmp/models/qwen36-nvfp4
VER="vllm 0.28.0"

if [[ ! -d "${LOCAL}" ]]; then
  echo "missing ${LOCAL}" | tee -a "${ROOT}/failures.md"
  exit 1
fi

stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  sleep 2
}

launch_server() {
  local name="$1"
  shift
  stop_server
  local log="${ROOT}/logs/vllm-${name}.log"
  echo "LAUNCH ${name} $(date -Is)"
  printf '%s\n' "$*" > "${ROOT}/configs/vllm-${name}.cmd"
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
    "${IMG}" vllm serve "$@" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      > "${log}" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      tail -50 "${log}" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then
      echo "waiting ${name} ${i} $(date -Is)"
      tail -1 "${log}" || true
    fi
    sleep 2
  done
  echo "TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  stop_server
  return 1
}

smoke_math() {
  curl -sS -m 240 "http://127.0.0.1:${PORT}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 12*17? Reply with the integer only.\"}],\"max_tokens\":64,\"temperature\":0}" \
    | tee "${ROOT}/raw/qwen36-nvfp4-smoke-131k.json"
  echo
}

run_bench() {
  local tag="$1" profiles="$2" concs="$3" duration="$4" mtp="$5" drafts="$6" ctx="$7"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${MODEL}" \
    --hf-id "${MODEL}" \
    --quantization NVFP4 \
    --engine vllm \
    --engine-version "${VER}" \
    --profiles "${profiles}" \
    --concurrencies "${concs}" \
    --mode sustained \
    --duration "${duration}" \
    --warmup 1 \
    --timeout 1800 \
    --tag "${tag}" \
    --context-configured "${ctx}" \
    --kv-cache fp8 \
    --attention flashinfer \
    --moe-backend marlin \
    --mtp "${mtp}" \
    --draft-tokens "${drafts}" \
    --thinking off \
    --raw-dir "${ROOT}/raw"
}

BASE=(
  "${LOCAL}"
  --served-model-name "${MODEL}"
  --max-model-len 131072
  --max-num-seqs 16
  --max-num-batched-tokens 8192
  --gpu-memory-utilization 0.32
  --kv-cache-dtype fp8
  --attention-backend flashinfer
  --moe-backend marlin
  --enable-chunked-prefill
  --enable-prefix-caching
  --enforce-eager
  --safetensors-load-strategy eager
  --reasoning-parser qwen3
)

if ! launch_server mtp0-131k "${BASE[@]}"; then
  echo "131k launch failed" | tee -a "${ROOT}/failures.md"
  exit 1
fi
grep -E "KV cache size|Maximum concurrency|Model loading took|Using 'MARLIN'|FLASHINFER|FLASH_ATTN" "${ROOT}/logs/vllm-mtp0-131k.log" | tee "${ROOT}/raw/qwen36-nvfp4-131k-kv.txt" || true
smoke_math || true
run_bench qwen36-nvfp4-mtp0-131k "A,B" "1,2,4,8,12" 60 off 0 131072 || echo "bench failed" | tee -a "${ROOT}/failures.md"
stop_server

if launch_server mtp1-131k "${BASE[@]}" --spec-method mtp --spec-tokens 1; then
  run_bench qwen36-nvfp4-mtp1-131k "A,B" "1,4,8" 60 mtp 1 131072 || true
  stop_server
fi
if launch_server mtp3-131k "${BASE[@]}" --spec-method mtp --spec-tokens 3; then
  run_bench qwen36-nvfp4-mtp3-131k "A" "1,4" 60 mtp 3 131072 || true
  stop_server
fi
echo "QWEN36 SERVE DONE $(date -Is)"
