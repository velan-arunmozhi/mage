#!/bin/bash
# vLLM 0.28 on GB10. Flags were checked against `vllm serve --help=all`.
# `--load-format fastsafetensors` is not a choice in this build.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
export PYTHONUNBUFFERED=1
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
VER="vllm 0.28.0"

if [[ ! -s "${IMG}" ]]; then
  echo "missing ${IMG}" | tee -a "${ROOT}/failures.md"
  exit 1
fi

stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    local pid
    pid="$(cat "${ROOT}/state/vllm.pid")"
    kill "${pid}" 2>/dev/null || true
    sleep 3
    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  # Match the interpreter line, not this script.
  pkill -f "/usr/local/bin/vllm serve" 2>/dev/null || true
  sleep 2
}

launch_server() {
  local name="$1"
  shift
  stop_server
  local log="${ROOT}/logs/vllm-${name}.log"
  local -a args
  args=(
    serve "${MODEL}"
    --host 127.0.0.1
    --port "${PORT}"
    --tensor-parallel-size 1
    --trust-remote-code
    "$@"
  )
  {
    echo "LAUNCH $(date -Is)"
    printf '%q ' "${args[@]}"
    echo
  } > "${ROOT}/configs/vllm-${name}.cmd"
  echo "LAUNCH ${name}: ${args[*]}"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --env HF_HOME=/root/.cache/huggingface \
    --env HUGGINGFACE_HUB_CACHE=/root/.cache/huggingface/hub \
    --env HF_HUB_DISABLE_XET=1 \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env TRITON_CACHE_DIR=/root/.cache/vllm/triton \
    --env PYTHONUNBUFFERED=1 \
    --env VLLM_MARLIN_USE_ATOMIC_ADD=1 \
    --env VLLM_USE_FLASHINFER_MOE_FP4=0 \
    "${IMG}" vllm "${args[@]}" > "${log}" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "VLLM READY ${name} after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "VLLM DIED ${name}"
      tail -80 "${log}" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 15 == 0 )); then
      echo "still waiting ${name} check ${i}"
      tail -2 "${log}" || true
    fi
    sleep 2
  done
  echo "VLLM TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  tail -40 "${log}" | tee -a "${ROOT}/failures.md"
  return 1
}

smoke_math() {
  curl -sS -m 180 "http://127.0.0.1:${PORT}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"nvidia/Qwen3.6-35B-A3B-NVFP4","messages":[{"role":"user","content":"What is 12*17? Reply with the integer only."}],"max_tokens":32,"temperature":0}' \
    | tee "${ROOT}/raw/qwen36-nvfp4-smoke.json"
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

COMMON=(
  --max-model-len 8192
  --max-num-seqs 4
  --max-num-batched-tokens 8192
  --gpu-memory-utilization 0.40
  --kv-cache-dtype fp8
  --attention-backend flashinfer
  --moe-backend marlin
  --enable-chunked-prefill
  --enable-prefix-caching
  --async-scheduling
  --reasoning-parser qwen3
  --enforce-eager
)

if launch_server smoke-eager "${COMMON[@]}"; then
  smoke_math || true
else
  echo "eager smoke with marlin/flashinfer failed; retry auto kernels" | tee -a "${ROOT}/failures.md"
  if ! launch_server smoke-auto \
      --max-model-len 8192 \
      --max-num-seqs 2 \
      --gpu-memory-utilization 0.35 \
      --enforce-eager; then
    echo "vLLM cannot start Qwen3.6 NVFP4" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
  smoke_math || true
fi
stop_server

FULL=(
  --max-model-len 131072
  --max-num-seqs 16
  --max-num-batched-tokens 8192
  --gpu-memory-utilization 0.45
  --kv-cache-dtype fp8
  --attention-backend flashinfer
  --moe-backend marlin
  --enable-chunked-prefill
  --enable-prefix-caching
  --async-scheduling
  --reasoning-parser qwen3
)

if launch_server mtp0-c131k "${FULL[@]}"; then
  run_bench qwen36-nvfp4-mtp0 "A,B" "1,2,4,8,12,16" 60 off 0 131072 \
    || echo "mtp0 bench failed" | tee -a "${ROOT}/failures.md"
else
  echo "131072 graph launch failed; retrying enforce-eager" | tee -a "${ROOT}/failures.md"
  if launch_server mtp0-c131k-eager "${FULL[@]}" --enforce-eager; then
    run_bench qwen36-nvfp4-mtp0-eager "A,B" "1,2,4,8" 60 off 0 131072 \
      || echo "eager bench failed" | tee -a "${ROOT}/failures.md"
  else
    echo "Qwen3.6 131072 serve failed" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
fi
stop_server

for drafts in 1 2 3; do
  if launch_server "mtp${drafts}-c131k" "${FULL[@]}" --spec-method mtp --spec-tokens "${drafts}"; then
    run_bench "qwen36-nvfp4-mtp${drafts}" "A,B" "1,4,8" 60 mtp "${drafts}" 131072 \
      || echo "mtp${drafts} bench failed" | tee -a "${ROOT}/failures.md"
  else
    echo "MTP ${drafts} with method=mtp failed" | tee -a "${ROOT}/failures.md"
    if launch_server "qwenmtp${drafts}" "${FULL[@]}" --spec-method qwen3_5_mtp --spec-tokens "${drafts}"; then
      run_bench "qwen36-nvfp4-qwenmtp${drafts}" "A" "1,4" 45 qwen3_5_mtp "${drafts}" 131072 \
        || true
    fi
  fi
  stop_server
done

echo "VLLM QWEN36 DONE $(date -Is)"
