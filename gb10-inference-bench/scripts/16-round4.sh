#!/bin/bash
# MTP3 long-context with the 0.45/24 KV pool, then a harder quality pair.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/16-round4.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw"
exec > >(tee -a "${LOG}") 2>&1
echo "ROUND4 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"

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
  sleep 3
}

prepare() {
  if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
  apptainer exec --nv "${IMG}" vllm --version
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
  printf '%s\n' "name=${name} seqs=${seqs} util=${util} spec=${spec}" > "${ROOT}/configs/round4-${name}.cmd"
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
      > "${ROOT}/logs/vllm-round4-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      grep -E "Available KV|KV cache size|consumed memory|CUDA graph memory|Model loading took" "${ROOT}/logs/vllm-round4-${name}.log" | tee "${ROOT}/raw/round4-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "ValueError|No available|Free memory" "${ROOT}/logs/vllm-round4-${name}.log" | tail -8 | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then echo "waiting ${name} ${i}"; fi
    sleep 2
  done
  echo "TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  return 1
}

kv_tokens() {
  local file="$1"
  grep "KV cache size" "${file}" | tail -1 | sed -n 's/.*KV cache size: \([0-9,]*\) tokens.*/\1/p' | tr -d ','
}

prepare
# Official NVIDIA GB10 checkpoint. Download overlaps the Qwen measurements.
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind /tmp/models:/tmp/models \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  "${IMG}" python3 "${ROOT}/scripts/download_nemotron.py" \
  > "${ROOT}/logs/nemotron-download.log" 2>&1 &
echo $! > "${ROOT}/state/nemotron-dl.pid"
echo "NEMOTRON DOWNLOAD pid=$(cat "${ROOT}/state/nemotron-dl.pid")"

SPEC3='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
if ! launch_qwen mtp3-u45-s24 "${SPEC3}" 24 0.45; then
  echo "known-good 0.45/24 MTP3 failed" | tee -a "${ROOT}/failures.md"
  exit 1
fi
kv=$(kv_tokens "${ROOT}/logs/vllm-round4-mtp3-u45-s24.log")
echo "MTP3 KV tokens=${kv}"
if [[ -z "${kv}" || "${kv}" -lt 600000 ]]; then
  echo "KV ${kv} below 600000; one retry at utilization 0.55" | tee -a "${ROOT}/failures.md"
  if launch_qwen mtp3-u55-s24 "${SPEC3}" 24 0.55; then
    kv=$(kv_tokens "${ROOT}/logs/vllm-round4-mtp3-u55-s24.log")
    echo "MTP3 retry KV tokens=${kv}"
  fi
fi
if [[ -n "${kv}" && "${kv}" -ge 600000 ]]; then
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp3-resident --draft-tokens 3 \
    --concurrency 4 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024 \
    || echo "mtp3 resident long failed" | tee -a "${ROOT}/failures.md"
else
  echo "refusing 4-way long test; KV ${kv} cannot hold four 118k contexts" | tee -a "${ROOT}/failures.md"
fi
python3 "${ROOT}/scripts/quality_hard.py" --model "${QWEN_MODEL}" --tag qwen36-mtp3 --thinking server-default --engine vllm --max-tokens 4096 \
  || echo "qwen hard quality failed" | tee -a "${ROOT}/failures.md"
stop_all

if launch_qwen mtp0-u45-s4 "" 4 0.45; then
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp0-overlap --draft-tokens 0 \
    --concurrency 4 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024 \
    || echo "mtp0 overlap long failed" | tee -a "${ROOT}/failures.md"
fi
stop_all

llama_env
"${LLAMA_SERVER}" -m "${QWEN35_2B_GGUF}" --alias qwen35-2b --host 127.0.0.1 --port 8080 \
  -ngl 999 -fa on -c 32768 -np 1 -t 20 --jinja --reasoning off \
  > "${ROOT}/logs/llama-2b-hard.log" 2>&1 &
echo $! > "${ROOT}/state/llama.pid"
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8080/health >/dev/null; then break; fi
  sleep 2
done
python3 "${ROOT}/scripts/quality_hard.py" --base-url http://127.0.0.1:8080 --model qwen35-2b --tag qwen35-2b --thinking off --engine llama.cpp --max-tokens 4096 \
  || echo "2b hard quality failed" | tee -a "${ROOT}/failures.md"
stop_all

if [[ -f "${ROOT}/state/nemotron-dl.pid" ]]; then
  echo "waiting for Nemotron download"
  wait "$(cat "${ROOT}/state/nemotron-dl.pid")" || echo "nemotron download failed" | tee -a "${ROOT}/failures.md"
fi
if [[ -f /tmp/models/nemotron-nvfp4/config.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
cfg = json.loads(Path("/tmp/models/nemotron-nvfp4/config.json").read_text())
text = json.dumps({k: cfg.get(k) for k in ("model_type", "max_position_embeddings", "max_seq_len", "architectures")}, default=str)
print("NEMOTRON_CONFIG", text)
Path("/scratch/scholar/billin19/gb10-inference-bench/raw/nemotron-config.txt").write_text(text + "\n")
PY
  NEMO=/tmp/models/nemotron-nvfp4
  SPEC_N=()
  if [[ -f /tmp/models/nemotron-dspark/config.json ]]; then
    SPEC_N=(--speculative-config '{"model":"/tmp/models/nemotron-dspark","num_speculative_tokens":3}')
  fi
  stop_all
  echo "LAUNCH nemotron $(date -Is)"
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
    "${IMG}" vllm serve "${NEMO}" \
      --served-model-name nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
      --gpu-memory-utilization 0.80 --kv-cache-dtype fp8 \
      --attention-backend flashinfer --moe-backend marlin \
      --mamba-backend flashinfer --mamba-cache-mode align \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager --reasoning-parser nemotron_v3 \
      ${SPEC_N[@]+"${SPEC_N[@]}"} \
      > "${ROOT}/logs/vllm-round4-nemotron.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  nemo_ok=0
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY nemotron after $((i * 2))s"
      grep -E "Available KV|KV cache size|consumed memory|CUDA graph memory|Model loading took|max_position" "${ROOT}/logs/vllm-round4-nemotron.log" | tee "${ROOT}/raw/nemotron-kv.txt" || true
      nemo_ok=1
      break
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED nemotron" | tee -a "${ROOT}/failures.md"
      tail -40 "${ROOT}/logs/vllm-round4-nemotron.log" | tee -a "${ROOT}/failures.md"
      break
    fi
    if (( i % 20 == 0 )); then echo "waiting nemotron ${i}"; fi
    sleep 2
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
      --thinking server-default \
      || echo "nemotron A failed" | tee -a "${ROOT}/failures.md"
    python3 "${ROOT}/scripts/bench_client.py" \
      --base-url "http://127.0.0.1:${PORT}" \
      --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
      --hf-id nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
      --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
      --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
      --tag nemotron-dspark --context-configured 131072 --kv-cache fp8 \
      --attention flashinfer --moe-backend marlin --mtp dspark --draft-tokens 3 \
      --thinking server-default \
      || echo "nemotron B failed" | tee -a "${ROOT}/failures.md"
    python3 "${ROOT}/scripts/long_concurrency.py" --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
      --mtp nemotron-dspark --draft-tokens 3 --concurrency 1 --target-tokens 118000 \
      --min-tokens 1024 --max-tokens 1024 \
      || echo "nemotron long failed" | tee -a "${ROOT}/failures.md"
    python3 "${ROOT}/scripts/quality_hard.py" --model nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 \
      --tag nemotron --thinking server-default --engine vllm --max-tokens 4096 \
      || echo "nemotron quality failed" | tee -a "${ROOT}/failures.md"
  fi
else
  echo "Nemotron weights missing" | tee -a "${ROOT}/failures.md"
  tail -30 "${ROOT}/logs/nemotron-download.log" | tee -a "${ROOT}/failures.md" || true
fi
stop_all
echo "ROUND4 DONE $(date -Is)"
