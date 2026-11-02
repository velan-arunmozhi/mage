#!/bin/bash
# The first vLLM loads hung inside safetensors mmap after the NFS prefetch.
# This retries with --safetensors-load-strategy eager, then a local-disk copy.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
VER="vllm 0.28.0"

stop_server() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    local pid
    pid="$(cat "${ROOT}/state/vllm.pid")"
    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  sleep 1
}

launch_server() {
  local name="$1"
  local wait_checks="$2"
  shift 2
  stop_server
  local log="${ROOT}/logs/vllm-${name}.log"
  echo "LAUNCH ${name}: $*"
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --bind /tmp/models:/tmp/models \
    --env HF_HOME=/root/.cache/huggingface \
    --env HUGGINGFACE_HUB_CACHE=/root/.cache/huggingface/hub \
    --env HF_HUB_DISABLE_XET=1 \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env PYTHONUNBUFFERED=1 \
    --env VLLM_MARLIN_USE_ATOMIC_ADD=1 \
    --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
    "${IMG}" vllm serve "$@" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      > "${log}" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 "${wait_checks}"); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      tail -40 "${log}" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 15 == 0 )); then
      echo "waiting ${name} ${i}"
      tail -1 "${log}" || true
    fi
    sleep 2
  done
  echo "TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  tail -15 "${log}" | tee -a "${ROOT}/failures.md"
  stop_server
  return 1
}

smoke_math() {
  local out="$1"
  curl -sS -m 180 "http://127.0.0.1:${PORT}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 12*17? Reply with the integer only.\"}],\"max_tokens\":32,\"temperature\":0}" \
    | tee "${out}"
  echo
}

run_bench() {
  local tag="$1"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${MODEL}" \
    --hf-id "${MODEL}" \
    --quantization NVFP4 \
    --engine vllm \
    --engine-version "${VER} safetensors-eager native-alloc" \
    --profiles A,B \
    --concurrencies 1,2,4,8 \
    --mode sustained \
    --duration 60 \
    --warmup 1 \
    --timeout 1800 \
    --tag "${tag}" \
    --context-configured 8192 \
    --kv-cache fp8 \
    --attention flashinfer \
    --moe-backend marlin \
    --mtp off \
    --thinking off \
    --raw-dir "${ROOT}/raw"
}

ARGS=(
  "${MODEL}"
  --max-model-len 8192
  --max-num-seqs 4
  --max-num-batched-tokens 8192
  --gpu-memory-utilization 0.40
  --kv-cache-dtype fp8
  --attention-backend flashinfer
  --moe-backend marlin
  --enable-chunked-prefill
  --enforce-eager
  --safetensors-load-strategy eager
  --reasoning-parser qwen3
)

if launch_server eager-native 240 "${ARGS[@]}"; then
  smoke_math "${ROOT}/raw/qwen36-nvfp4-eager-smoke.json" || true
  run_bench qwen36-nvfp4-eager-c8192 || echo "bench failed" | tee -a "${ROOT}/failures.md"
  stop_server
  echo "EAGER PATH DONE $(date -Is)"
  exit 0
fi

echo "eager strategy failed; copying checkpoint to local NVMe" | tee -a "${ROOT}/failures.md"
SNAP=$(find "${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots" -mindepth 1 -maxdepth 1 -type d | head -1)
echo "snapshot ${SNAP}"
mkdir -p /tmp/models
rm -rf /tmp/models/qwen36-nvfp4
mkdir -p /tmp/models/qwen36-nvfp4
# Dereference HF symlinks so the local copy does not point back at NFS.
cp -aL "${SNAP}/." /tmp/models/qwen36-nvfp4/
du -sh /tmp/models/qwen36-nvfp4

if launch_server local-nvme 240 \
    /tmp/models/qwen36-nvfp4 \
    --max-model-len 8192 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.40 \
    --kv-cache-dtype fp8 \
    --moe-backend marlin \
    --attention-backend flashinfer \
    --enforce-eager \
    --safetensors-load-strategy eager \
    --served-model-name "${MODEL}"; then
  smoke_math "${ROOT}/raw/qwen36-nvfp4-local-smoke.json" || true
  run_bench qwen36-nvfp4-local || true
  stop_server
  exit 0
fi

echo "NVFP4 load failed on NFS eager and local eager" | tee -a "${ROOT}/failures.md"
# Small safetensors control, to separate a broken vLLM from a large-checkpoint hang.
if launch_server tiny 180 Qwen/Qwen2.5-0.5B-Instruct --max-model-len 2048 --enforce-eager --gpu-memory-utilization 0.15 --max-num-seqs 1; then
  echo "tiny model became healthy; vLLM itself can serve" | tee -a "${ROOT}/failures.md"
  curl -sS -m 60 "http://127.0.0.1:${PORT}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"12*17"}],"max_tokens":16,"temperature":0}' \
    | tee "${ROOT}/raw/tiny-vllm-smoke.json"
  echo
  stop_server
fi
echo "WORKAROUND STAGE DONE $(date -Is)"
