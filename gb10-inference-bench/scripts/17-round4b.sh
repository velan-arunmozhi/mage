#!/bin/bash
# Paired MTP0 long-context run, dedented quality rescore, and Nemotron if still missing.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/17-round4b.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "ROUND4B START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"

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

prepare() {
  if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
  if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
    mkdir -p "${QWEN_LOCAL}"
    cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
  fi
}

launch_qwen() {
  local name="$1" spec="$2" seqs="$3" util="$4"
  stop_all
  echo "LAUNCH ${name} seqs=${seqs} util=${util} $(date -Is)"
  free -h
  local -a spec_args=()
  if [[ -n "${spec}" ]]; then spec_args=(--speculative-config "${spec}"); fi
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
    "${IMG}" vllm serve "${QWEN_LOCAL}" \
      --served-model-name "${QWEN_MODEL}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer --moe-backend marlin \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager --reasoning-parser qwen3 \
      ${spec_args[@]+"${spec_args[@]}"} \
      > "${ROOT}/logs/vllm-round4b-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      grep -E "Available KV|KV cache size|consumed memory" "${ROOT}/logs/vllm-round4b-${name}.log" | tee "${ROOT}/raw/round4b-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}" | tee -a "${ROOT}/failures.md"
      grep -E "ValueError|Free memory" "${ROOT}/logs/vllm-round4b-${name}.log" | tail -8 | tee -a "${ROOT}/failures.md"
      return 1
    fi
    sleep 2
  done
  return 1
}

prepare
if ! grep -q "long-mtp0-overlap" "${ROOT}/results.jsonl"; then
  if launch_qwen mtp0-u45-s4 "" 4 0.45; then
    python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp0-overlap --draft-tokens 0 \
      --concurrency 4 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024 \
      || echo "mtp0 overlap failed" | tee -a "${ROOT}/failures.md"
    python3 "${ROOT}/scripts/quality_hard.py" --model "${QWEN_MODEL}" --tag qwen36-mtp0-think --thinking server-default --engine vllm --max-tokens 4096 \
      || echo "qwen think quality failed" | tee -a "${ROOT}/failures.md"
    python3 "${ROOT}/scripts/quality_hard.py" --model "${QWEN_MODEL}" --tag qwen36-mtp0-nothink --thinking off --engine vllm --max-tokens 4096 \
      || echo "qwen nothink quality failed" | tee -a "${ROOT}/failures.md"
  fi
fi
stop_all

llama_env
"${LLAMA_SERVER}" -m "${QWEN35_2B_GGUF}" --alias qwen35-2b --host 127.0.0.1 --port 8080 \
  -ngl 999 -fa on -c 32768 -np 1 -t 20 --jinja --reasoning off \
  > "${ROOT}/logs/llama-2b-hard2.log" 2>&1 &
echo $! > "${ROOT}/state/llama.pid"
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8080/health >/dev/null; then break; fi
  sleep 2
done
python3 "${ROOT}/scripts/quality_hard.py" --base-url http://127.0.0.1:8080 --model qwen35-2b --tag qwen35-2b-rescore --thinking off --engine llama.cpp --max-tokens 4096 \
  || echo "2b rescore failed" | tee -a "${ROOT}/failures.md"
stop_all

if grep -q "nemotron-dspark-A-c16" "${ROOT}/results.jsonl"; then
  echo "Nemotron short-context result already recorded"
else
  if [[ ! -f /tmp/models/nemotron-nvfp4/config.json ]]; then
    apptainer exec --nv \
      --bind "${HF_HOME}:/root/.cache/huggingface" \
      --bind /tmp/models:/tmp/models \
      --env HF_HOME=/root/.cache/huggingface \
      --env PYTHONUNBUFFERED=1 \
      "${IMG}" python3 "${ROOT}/scripts/download_nemotron.py" \
      > "${ROOT}/logs/nemotron-download-b.log" 2>&1 || echo "nemotron download failed" | tee -a "${ROOT}/failures.md"
  fi
  if [[ -f /tmp/models/nemotron-nvfp4/config.json ]]; then
    SPEC_N=()
    if [[ -f /tmp/models/nemotron-dspark/config.json ]]; then
      SPEC_N=(--speculative-config '{"model":"/tmp/models/nemotron-dspark","num_speculative_tokens":3}')
    fi
    nemo_ok=0
    for util in 0.70 0.45; do
      stop_all
      echo "LAUNCH nemotron-b util=${util} $(date -Is)"
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
        "${IMG}" vllm serve /tmp/models/nemotron-nvfp4 \
          --served-model-name nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
          --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
          --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
          --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
          --attention-backend flashinfer --moe-backend marlin \
          --mamba-backend flashinfer --mamba-cache-mode align \
          --enable-chunked-prefill --enable-prefix-caching \
          --safetensors-load-strategy eager --reasoning-parser nemotron_v3 \
          ${SPEC_N[@]+"${SPEC_N[@]}"} \
          > "${ROOT}/logs/vllm-round4b-nemotron-${util}.log" 2>&1 &
      echo $! > "${ROOT}/state/vllm.pid"
      for i in $(seq 1 900); do
        if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
          echo "READY nemotron-b util=${util} after $((i * 2))s"
          grep -E "Available KV|KV cache size|consumed memory|Model loading took" "${ROOT}/logs/vllm-round4b-nemotron-${util}.log" | tee "${ROOT}/raw/nemotron-b-kv.txt" || true
          nemo_ok=1
          break
        fi
        if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
          echo "DIED nemotron-b util=${util}" | tee -a "${ROOT}/failures.md"
          grep -E "ValueError|Free memory|Error" "${ROOT}/logs/vllm-round4b-nemotron-${util}.log" | tail -8 | tee -a "${ROOT}/failures.md"
          break
        fi
        sleep 2
      done
      if [[ "${nemo_ok}" == 1 ]]; then
        break
      fi
    done
    if [[ "${nemo_ok}" == 1 ]]; then
      python3 "${ROOT}/scripts/bench_client.py" \
        --base-url "http://127.0.0.1:${PORT}" \
        --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --hf-id nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
        --profiles A --concurrencies 1,8,16 --mode sustained --duration 60 --warmup 1 \
        --tag nemotron-dspark --context-configured 131072 --kv-cache fp8 \
        --attention flashinfer --moe-backend marlin --mtp dspark --draft-tokens 3 \
        --thinking server-default || echo "nemotron A failed" | tee -a "${ROOT}/failures.md"
      python3 "${ROOT}/scripts/bench_client.py" \
        --base-url "http://127.0.0.1:${PORT}" \
        --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --hf-id nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
        --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
        --tag nemotron-dspark --context-configured 131072 --kv-cache fp8 \
        --attention flashinfer --moe-backend marlin --mtp dspark --draft-tokens 3 \
        --thinking server-default || echo "nemotron B failed" | tee -a "${ROOT}/failures.md"
      python3 "${ROOT}/scripts/long_concurrency.py" --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --mtp nemotron-dspark --draft-tokens 3 --concurrency 1 --target-tokens 118000 \
        --min-tokens 1024 --max-tokens 1024 || echo "nemotron long failed" | tee -a "${ROOT}/failures.md"
      python3 "${ROOT}/scripts/quality_hard.py" --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
        --tag nemotron --thinking server-default --engine vllm --max-tokens 4096 || echo "nemotron quality failed" | tee -a "${ROOT}/failures.md"
    fi
  fi
fi
stop_all
echo "ROUND4B DONE $(date -Is)"
