#!/bin/bash
# Stage 1: vLLM Qwen3.6-35B-A3B NVFP4 on the GB10, MTP sweep and concurrency.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG="/tmp/vllm-apptainer/vllm-openai-0.28.0.sif"
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
mkdir -p "${ROOT}/vllm-cache" "${ROOT}/tmp" "${ROOT}/hf-run"

wait_for_image() {
  mkdir -p /tmp/vllm-apptainer/cache /tmp/vllm-apptainer/tmp
  if [[ ! -s "${IMG}" ]] && ! pgrep -f "apptainer pull .*vllm-openai-0.28.0.sif" >/dev/null; then
    echo "starting compute-node image pull into /tmp (scratch is nodev)"
    export APPTAINER_CACHEDIR=/tmp/vllm-apptainer/cache
    export APPTAINER_TMPDIR=/tmp/vllm-apptainer/tmp
    nohup apptainer pull "${IMG}" docker://vllm/vllm-openai:v0.28.0 \
      > "${ROOT}/logs/01-pull-vllm-node.out" 2>&1 &
    echo $! > "${ROOT}/state/pull-node.pid"
  fi
  local start now
  start=$(date +%s)
  echo "waiting for ${IMG}"
  while [[ ! -s "${IMG}" ]]; do
    now=$(date +%s)
    if (( now - start > 3600 )); then
      echo "image wait exceeded 60 min" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if [[ -f "${ROOT}/logs/01-pull-vllm-node.out" ]] && grep -E -q "FATAL|error building image" "${ROOT}/logs/01-pull-vllm-node.out"; then
      local age
      age=$(( now - $(stat -c %Y "${ROOT}/logs/01-pull-vllm-node.out") ))
      if (( age > 120 )); then
        echo "node pull failed" | tee -a "${ROOT}/failures.md"
        tail -40 "${ROOT}/logs/01-pull-vllm-node.out" | tee -a "${ROOT}/failures.md"
        return 1
      fi
    fi
    sleep 20
  done
  echo "image ready $(date -Is) size=$(stat -c %s "${IMG}")"
  # Keep a scratch copy for the next allocation. Copy is best-effort.
  if [[ ! -s "${VLLM_SIF}" ]]; then
    cp -n "${IMG}" "${VLLM_SIF}" || echo "scratch copy of sif failed" | tee -a "${ROOT}/failures.md"
  fi
}

stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    local pid
    pid="$(cat "${ROOT}/state/vllm.pid")"
    kill "${pid}" 2>/dev/null || true
    sleep 5
    kill -9 "${pid}" 2>/dev/null || true
    # Apptainer may leave the inner vLLM process.
    pkill -f "vllm serve ${MODEL}" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  sleep 3
}

vllm_help() {
  if [[ -f "${ROOT}/state/vllm-help.txt" ]]; then
    return 0
  fi
  apptainer exec --nv "${IMG}" vllm serve --help > "${ROOT}/state/vllm-help.txt" 2>&1 || true
  apptainer exec --nv "${IMG}" vllm --version > "${ROOT}/state/vllm-version.txt" 2>&1 || true
}

has_flag() {
  grep -q -- "$1" "${ROOT}/state/vllm-help.txt"
}

launch_server() {
  local name="$1" maxlen="$2" seqs="$3" spec="$4" util="$5"
  stop_server
  local log="${ROOT}/logs/vllm-${name}.log"
  local -a args
  args=(serve "${MODEL}" --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code)
  has_flag --max-model-len && args+=(--max-model-len "${maxlen}")
  has_flag --max-num-seqs && args+=(--max-num-seqs "${seqs}")
  has_flag --max-num-batched-tokens && args+=(--max-num-batched-tokens 8192)
  has_flag --gpu-memory-utilization && args+=(--gpu-memory-utilization "${util}")
  has_flag --kv-cache-dtype && args+=(--kv-cache-dtype fp8)
  has_flag --attention-backend && args+=(--attention-backend flashinfer)
  has_flag --moe-backend && args+=(--moe-backend marlin)
  has_flag --enable-chunked-prefill && args+=(--enable-chunked-prefill)
  has_flag --enable-prefix-caching && args+=(--enable-prefix-caching)
  has_flag --async-scheduling && args+=(--async-scheduling)
  has_flag --load-format && args+=(--load-format fastsafetensors)
  has_flag --reasoning-parser && args+=(--reasoning-parser qwen3)
  if [[ -n "${spec}" ]]; then
    has_flag --speculative-config && args+=(--speculative-config "${spec}")
  fi
  printf '%q ' apptainer exec --nv "${args[@]}" > "${ROOT}/configs/vllm-${name}.cmd"
  echo >> "${ROOT}/configs/vllm-${name}.cmd"
  echo "LAUNCH ${name}: ${args[*]}"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --env HF_HOME=/root/.cache/huggingface \
    --env HUGGINGFACE_HUB_CACHE=/root/.cache/huggingface/hub \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env TRITON_CACHE_DIR=/root/.cache/vllm/triton \
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
      tail -60 "${log}" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 30 == 0 )); then
      echo "still waiting ${name} ${i}"
      tail -3 "${log}" || true
    fi
    sleep 2
  done
  echo "VLLM TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  tail -40 "${log}" | tee -a "${ROOT}/failures.md"
  return 1
}

smoke() {
  local body='{"model":"nvidia/Qwen3.6-35B-A3B-NVFP4","messages":[{"role":"user","content":"What is 12*17? Reply with the integer only."}],"max_tokens":64,"temperature":0}'
  curl -sS -m 180 http://127.0.0.1:${PORT}/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d "${body}" | tee "${ROOT}/raw/qwen36-nvfp4-smoke.json"
  echo
}

run_bench() {
  local tag="$1" profiles="$2" concs="$3" duration="$4" mtp="$5" drafts="$6" ctx="$7"
  local ver
  ver="$(tr '\n' ' ' < "${ROOT}/state/vllm-version.txt" 2>/dev/null || true)"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${MODEL}" \
    --hf-id "${MODEL}" \
    --quantization NVFP4 \
    --engine vllm \
    --engine-version "${ver}" \
    --profiles "${profiles}" \
    --concurrencies "${concs}" \
    --mode sustained \
    --duration "${duration}" \
    --warmup 1 \
    --timeout 1200 \
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

# The cached Qwen3.6 GGUF aborted inside CUDA weight upload on this driver.
# Try load modes before spending the allocation only on vLLM.
diagnose_qwen36_gguf() {
  llama_env
  export CUDA_LAUNCH_BLOCKING=1
  local mode
  for mode in none mmap dio; do
    echo "TRY qwen36 -lm ${mode} $(date -Is)"
    if timeout 240 "${LLAMA_BENCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa off -lm "${mode}" -t 20 -r 1 --progress -o jsonl \
        -p 128 -n 32 > "${ROOT}/raw/qwen36-lm-${mode}.jsonl" 2> "${ROOT}/raw/qwen36-lm-${mode}.err"; then
      echo "qwen36 load mode ${mode} worked" | tee -a "${ROOT}/logs/qwen36-load-mode.txt"
      timeout 1200 "${LLAMA_BENCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa on -lm "${mode}" -t 20 -r 2 --progress -o jsonl \
        -pg 1024,512 -pg 8192,256 > "${ROOT}/raw/qwen36-retry-${mode}.jsonl" 2> "${ROOT}/raw/qwen36-retry-${mode}.err" || true
      python3 "${ROOT}/scripts/ingest_llama_bench.py" --kind bench \
        --path "${ROOT}/raw/qwen36-retry-${mode}.jsonl" \
        --model "Qwen3.6-35B-A3B" --hf-id "unsloth/Qwen3.6-35B-A3B-GGUF" \
        --quant "UD-Q4_K_M" --engine-version "retry-lm-${mode}" || true
      return 0
    fi
    echo "qwen36 -lm ${mode} failed" | tee -a "${ROOT}/failures.md"
    tail -15 "${ROOT}/raw/qwen36-lm-${mode}.err" | tee -a "${ROOT}/failures.md" || true
  done
  return 1
}

diagnose_qwen36_gguf || echo "all qwen36 GGUF load modes failed; continuing to vLLM" | tee -a "${ROOT}/failures.md"

wait_for_image || exit 1
vllm_help
echo "----- vllm version -----"
cat "${ROOT}/state/vllm-version.txt" || true

if launch_server smoke 8192 4 "" 0.40; then
  smoke || true
  run_bench qwen36-nvfp4-mtp0-smoke A 1 30 off 0 8192 || echo "smoke bench failed" | tee -a "${ROOT}/failures.md"
else
  echo "smoke launch failed; retrying without fastsafetensors and speculative defaults" | tee -a "${ROOT}/failures.md"
  # Second attempt: eager, lower memory, shorter context, no optional kernels.
  stop_server
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --env HF_HOME=/root/.cache/huggingface \
    --env VLLM_MARLIN_USE_ATOMIC_ADD=1 \
    --env VLLM_USE_FLASHINFER_MOE_FP4=0 \
    "${IMG}" vllm serve "${MODEL}" \
      --host 127.0.0.1 --port "${PORT}" --trust-remote-code \
      --max-model-len 8192 --max-num-seqs 2 --gpu-memory-utilization 0.35 \
      --enforce-eager \
      > "${ROOT}/logs/vllm-smoke-eager.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  ok=0
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then ok=1; break; fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then break; fi
    sleep 2
  done
  if [[ "${ok}" != 1 ]]; then
    echo "eager smoke also failed" | tee -a "${ROOT}/failures.md"
    tail -80 "${ROOT}/logs/vllm-smoke-eager.log" | tee -a "${ROOT}/failures.md"
    exit 1
  fi
  smoke || true
fi
stop_server

if launch_server mtp0-c131k 131072 16 "" 0.45; then
  run_bench qwen36-nvfp4-mtp0 "A,B" "1,2,4,8,12,16" 60 off 0 131072 || echo "mtp0 sweep failed" | tee -a "${ROOT}/failures.md"
else
  echo "131072 MTP-off launch failed" | tee -a "${ROOT}/failures.md"
  exit 1
fi
stop_server

for drafts in 1 2 3; do
  spec="{\"method\":\"mtp\",\"num_speculative_tokens\":${drafts},\"moe_backend\":\"triton\"}"
  if launch_server "mtp${drafts}-c131k" 131072 16 "${spec}" 0.45; then
    run_bench "qwen36-nvfp4-mtp${drafts}" "A,B" "1,4,8" 60 mtp "${drafts}" 131072 || echo "mtp${drafts} bench failed" | tee -a "${ROOT}/failures.md"
  else
    echo "MTP ${drafts} failed to launch" | tee -a "${ROOT}/failures.md"
  fi
  stop_server
done

echo "VLLM QWEN36 STAGE COMPLETE $(date -Is)"
