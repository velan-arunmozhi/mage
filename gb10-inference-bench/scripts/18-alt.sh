#!/bin/bash
# Nemotron without DSpark, then LFM2.5 only if Nemotron does not serve or is far slower.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
NEMO_MODEL="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
NEMO_LOCAL=/tmp/models/nemotron-nvfp4
LOG="${ROOT}/logs/18-alt.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "ALT START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"

stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 8
}

record_fail() {
  local id="$1" model="$2" note="$3"
  python3 - <<PY
import json, sys
sys.path.insert(0, "${ROOT}/scripts")
from record import append_jsonl, write_csv_row, RESULTS_JSONL
obj = {
    "experiment_id": "${id}",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "status": "fail",
    "model": "${model}",
    "hf_id": "${model}",
    "quantization": "NVFP4",
    "engine": "vllm",
    "engine_version": "0.28.0",
    "profile": "startup",
    "context_configured": 131072,
    "mode": "serve",
    "mtp": "off",
    "notes": json.dumps(${note}),
}
append_jsonl(RESULTS_JSONL, obj)
write_csv_row(obj)
print("RECORDED_FAIL", obj["experiment_id"])
PY
}

cuda_free() {
  apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(f,t)'
}

choose_util() {
  local free total
  read -r free total < <(cuda_free)
  printf 'CUDA_FREE bytes=%s total=%s\n' "${free}" "${total}" > "${ROOT}/raw/alt-cuda-free.txt"
  python3 -c 'free=int("'"${free}"'"); total=int("'"${total}"'"); print(f"{min(0.40, (free / total) * 0.80):.2f}")'
}

prepare_nemo() {
  if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
  apptainer exec --nv "${IMG}" vllm --version
  # A previous empty-path copy wrote the filesystem root into this directory.
  if [[ -d "${NEMO_LOCAL}" && ! -f "${NEMO_LOCAL}/config.json" ]]; then
    echo "REMOVE poisoned ${NEMO_LOCAL}"
    rm -rf "${NEMO_LOCAL}"
  fi
  if [[ ! -f "${NEMO_LOCAL}/config.json" ]]; then
    echo "DOWNLOAD nemotron into the HF cache"
    apptainer exec --nv \
      --bind "${HF_HOME}:/root/.cache/huggingface" \
      --env HF_HOME=/root/.cache/huggingface \
      --env PYTHONUNBUFFERED=1 \
      "${IMG}" python3 - <<PY
from huggingface_hub import snapshot_download
path = snapshot_download("${NEMO_MODEL}")
print("NEMOTRON_CACHE", path)
PY
    local snap
    snap=$(find "${HF_HOME}/hub/models--nvidia--NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
    if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then
      echo "Nemotron snapshot missing after download" | tee -a "${ROOT}/failures.md"
      exit 1
    fi
    echo "COPY nemotron from ${snap}"
    mkdir -p "${NEMO_LOCAL}"
    cp -aL "${snap}/." "${NEMO_LOCAL}/"
  fi
  python3 - <<PY
import json
from pathlib import Path
cfg=json.loads(Path("${NEMO_LOCAL}/config.json").read_text())
text=json.dumps({k: cfg.get(k) for k in ("model_type","architectures","max_position_embeddings")})
print("NEMO_CONFIG", text)
Path("${ROOT}/raw/nemotron-config-alt.txt").write_text(text+"\n")
PY
}

# name seqs util model_len extra_env logfile
launch_nemo() {
  local name="$1" seqs="$2" util="$3" model_len="$4" extra_env="$5"
  stop_all
  echo "LAUNCH ${name} seqs=${seqs} util=${util} len=${model_len} env=${extra_env} $(date -Is)"
  free -h
  printf '%s\n' "name=${name} seqs=${seqs} util=${util} len=${model_len} spec=off mamba_dtype=float16 ${extra_env}" > "${ROOT}/configs/alt-${name}.cmd"
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
    --env CUDA_LAUNCH_BLOCKING="${extra_env}" \
    "${IMG}" vllm serve "${NEMO_LOCAL}" \
      --served-model-name "${NEMO_MODEL}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len "${model_len}" --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer --moe-backend marlin \
      --mamba-backend flashinfer --mamba-cache-mode align \
      --mamba-ssm-cache-dtype float16 \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager --reasoning-parser nemotron_v3 \
      > "${ROOT}/logs/vllm-alt-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      grep -E "Available KV|KV cache size|consumed memory|Model loading took|mamba_ssm" "${ROOT}/logs/vllm-alt-${name}.log" | tee "${ROOT}/raw/alt-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "ValueError|Error|illegal|Free memory|NotImplemented|not supported" "${ROOT}/logs/vllm-alt-${name}.log" | tail -20 | tee "${ROOT}/raw/alt-${name}-error.txt"
      return 1
    fi
    if (( i % 30 == 0 )); then echo "waiting ${name} ${i}"; fi
    sleep 2
  done
  echo "TIMEOUT ${name}"
  return 1
}

smoke() {
  local body='{"model":"'"${NEMO_MODEL}"'","messages":[{"role":"user","content":"Reply with the single word pong."}],"max_tokens":32,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}'
  local out
  out=$(curl -sf "http://127.0.0.1:${PORT}/v1/chat/completions" -H 'Content-Type: application/json' -d "${body}" || true)
  echo "SMOKE ${out}" | head -c 2000
  echo
  echo "${out}" | grep -qi pong
}

bench_nemo() {
  local tag="$1" draft="$2"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${NEMO_MODEL}" --hf-id "${NEMO_MODEL}" \
    --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
    --profiles A --concurrencies 1,8,16 --mode sustained --duration 60 --warmup 1 \
    --tag "${tag}" --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend marlin --mtp "${tag}" --draft-tokens "${draft}" \
    --thinking off \
    || echo "bench A ${tag} failed"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${NEMO_MODEL}" --hf-id "${NEMO_MODEL}" \
    --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
    --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
    --tag "${tag}" --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend marlin --mtp "${tag}" --draft-tokens "${draft}" \
    --thinking off \
    || echo "bench B ${tag} failed"
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${NEMO_MODEL}" \
    --mtp "${tag}" --draft-tokens "${draft}" --concurrency 1 --target-tokens 118000 \
    --min-tokens 1024 --max-tokens 1024 \
    || echo "long ${tag} failed"
}

agg_of() {
  local needle="$1"
  grep "RESULT ${needle}" "${LOG}" | tail -1 | sed -n 's/.*agg=\([0-9.]*\).*/\1/p'
}

prepare_nemo
UTIL=$(choose_util)
echo "CHOSEN_UTIL ${UTIL}"
NEMO_OK=0
if launch_nemo nospec-s4 4 "${UTIL}" 131072 0; then
  if smoke; then
    echo "SMOKE_OK"
    # max-num-seqs 16 crashed while allocating the KV tensor after Mamba2 warmup.
    # Measure on this live 4-sequence server. 8 and 16 clients will queue.
    NEMO_OK=1
    BENCH_TAG=nemotron-nospec-s4
  else
    echo "SMOKE_FAIL" | tee "${ROOT}/raw/alt-smoke-fail.txt"
  fi
fi

if [[ "${NEMO_OK}" != 1 ]]; then
  echo "DIAGNOSTIC CUDA_LAUNCH_BLOCKING max-model-len 8192"
  if launch_nemo block-8k 1 "${UTIL}" 8192 1; then
    echo "SHORT_CONTEXT_STARTED"
    stop_all
    echo "short context started; one return to 131072 without blocking"
    launch_nemo nospec-s4-retry 4 "${UTIL}" 131072 0 && NEMO_OK=1 && BENCH_TAG=nemotron-nospec || true
  else
    echo "BLOCKING_DIAGNOSTIC_FAILED"
    tail -30 "${ROOT}/logs/vllm-alt-block-8k.log" | tee "${ROOT}/raw/alt-block-8k-tail.txt" || true
  fi
fi

if [[ "${NEMO_OK}" != 1 && -n "${UTIL}" ]]; then
  echo "TRY vLLM 0.27.1 once, no DSpark, separate image"
  SIF27=/tmp/vllm-apptainer/vllm-openai-0.27.1.sif
  if [[ ! -s "${SIF27}" ]]; then
    apptainer pull "${SIF27}" docker://vllm/vllm-openai:v0.27.1 || echo "pull 0.27.1 failed"
  fi
  if [[ -s "${SIF27}" ]]; then
    IMG_SAVED="${IMG}"
    IMG="${SIF27}"
    if launch_nemo v0271-nospec 4 "${UTIL}" 131072 0; then
      NEMO_OK=1
      BENCH_TAG=nemotron-v0271
    else
      IMG="${IMG_SAVED}"
    fi
  fi
fi

if [[ "${NEMO_OK}" != 1 ]]; then
  record_fail "nemotron-nospec-startup-$(date -u +%Y%m%dT%H%M%SZ)" "${NEMO_MODEL}" '{"spec":"off","attempts":["nospec-s4-131072","blocking-8192","vllm-0.27.1"],"blocker":"see logs/vllm-alt-*.log"}'
  echo "NEMOTRON_BLOCKED"
else
  if smoke; then echo "BENCH_SMOKE_OK"; else echo "BENCH_SMOKE_FAIL"; fi
  bench_nemo "${BENCH_TAG}" 0
  python3 "${ROOT}/scripts/quality_hard.py" --model "${NEMO_MODEL}" --tag nemotron-nospec --thinking off --engine vllm --max-tokens 4096 \
    || echo "nemotron quality failed"
  A16=$(agg_of "${BENCH_TAG}-A-c16")
  echo "NEMOTRON_A16 ${A16}"
  # DSpark only if the no-draft result approaches Qwen's 581 tok/s.
  awk -v a="${A16:-0}" 'BEGIN{exit !(a+0 >= 450)}' && {
    echo "DSPARK retry once; no-draft aggregate was ${A16}"
    DSPARK=/tmp/models/nemotron-dspark
    if [[ ! -f "${DSPARK}/config.json" ]]; then
      snap=$(find "${HF_HOME}/hub/models--nvidia--NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
      if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then
        echo "DSpark snapshot missing; skip"
      else
      mkdir -p "${DSPARK}"
      cp -aL "${snap}/." "${DSPARK}/"
      fi
    fi
    stop_all
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
      "${IMG}" vllm serve "${NEMO_LOCAL}" \
        --served-model-name "${NEMO_MODEL}" \
        --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
        --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
        --gpu-memory-utilization "${UTIL}" --kv-cache-dtype fp8 \
        --attention-backend flashinfer --moe-backend marlin \
        --mamba-backend flashinfer --mamba-cache-mode align \
        --mamba-ssm-cache-dtype float16 \
        --enable-chunked-prefill --enable-prefix-caching \
        --safetensors-load-strategy eager --reasoning-parser nemotron_v3 \
        --speculative-config '{"model":"/tmp/models/nemotron-dspark","num_speculative_tokens":3}' \
        > "${ROOT}/logs/vllm-alt-dspark.log" 2>&1 &
    echo $! > "${ROOT}/state/vllm.pid"
    ds_ok=0
    for i in $(seq 1 900); do
      if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then ds_ok=1; echo "READY dspark"; break; fi
      if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then echo "DIED dspark"; break; fi
      sleep 2
    done
    if [[ "${ds_ok}" == 1 ]]; then
      python3 "${ROOT}/scripts/bench_client.py" \
        --base-url "http://127.0.0.1:${PORT}" \
        --model "${NEMO_MODEL}" --hf-id "${NEMO_MODEL}" \
        --quantization NVFP4 --engine vllm --engine-version 0.28.0 \
        --profiles A --concurrencies 1,8,16 --mode sustained --duration 60 --warmup 1 \
        --tag nemotron-dspark --context-configured 131072 --kv-cache fp8 \
        --attention flashinfer --moe-backend marlin --mtp dspark --draft-tokens 3 \
        --thinking off || echo "dspark bench failed"
    else
      grep -E "illegal|ValueError|Error" "${ROOT}/logs/vllm-alt-dspark.log" | tail -15 | tee "${ROOT}/raw/alt-dspark-error.txt" || true
    fi
  } || echo "DSPARK skipped; A16=${A16:-none} is below 450"
fi
stop_all

# LFM only when Nemotron did not serve, or its 16-client short-prompt rate is well under Qwen.
NEED_LFM=0
if [[ "${NEMO_OK}" != 1 ]]; then NEED_LFM=1; fi
if [[ -n "${A16:-}" ]]; then
  awk -v a="${A16:-0}" 'BEGIN{exit !(a+0 < 400)}' && NEED_LFM=1
fi
if [[ "${NEED_LFM}" != 1 ]]; then
  echo "LFM skipped; Nemotron is close to Qwen"
  echo "ALT DONE $(date -Is)"
  exit 0
fi

if [[ -n "${IMG_SAVED:-}" ]]; then IMG="${IMG_SAVED}"; fi
echo "LFM START $(date -Is)"
LFM_MODEL="LiquidAI/LFM2.5-24B-A2B-FP8"
LFM_LOCAL=/tmp/models/lfm25-fp8
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind /tmp/models:/tmp/models \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  "${IMG}" python3 - <<PY
from huggingface_hub import snapshot_download
path=snapshot_download("${LFM_MODEL}", local_dir="${LFM_LOCAL}")
print("LFM_DOWNLOAD_OK", path)
PY
if [[ ! -f "${LFM_LOCAL}/config.json" ]]; then
  echo "LFM download failed" | tee -a "${ROOT}/failures.md"
  echo "ALT DONE $(date -Is)"
  exit 0
fi
python3 - <<PY
import json
from pathlib import Path
cfg=json.loads(Path("${LFM_LOCAL}/config.json").read_text())
print("LFM_CONFIG", json.dumps({k: cfg.get(k) for k in ("model_type","architectures","max_position_embeddings")}))
PY
stop_all
echo "LAUNCH lfm-0.28 $(date -Is)"
apptainer exec --nv \
  --bind "${HF_HOME}:/root/.cache/huggingface" \
  --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
  --bind "${ROOT}/tmp:/tmp" \
  --bind /tmp/models:/tmp/models \
  --env HF_HOME=/root/.cache/huggingface \
  --env PYTHONUNBUFFERED=1 \
  --env VLLM_CACHE_ROOT=/root/.cache/vllm \
  --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
  "${IMG}" vllm serve "${LFM_LOCAL}" \
    --served-model-name "${LFM_MODEL}" \
    --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
    --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
    --gpu-memory-utilization 0.45 --kv-cache-dtype fp8 \
    --enable-chunked-prefill --enable-prefix-caching \
    --safetensors-load-strategy eager \
    > "${ROOT}/logs/vllm-alt-lfm-028.log" 2>&1 &
echo $! > "${ROOT}/state/vllm.pid"
lfm_ok=0
for i in $(seq 1 600); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "READY lfm-0.28"
    grep -E "KV cache size|Available KV|Model loading|Error|not support" "${ROOT}/logs/vllm-alt-lfm-028.log" | tee "${ROOT}/raw/alt-lfm-kv.txt" || true
    lfm_ok=1
    break
  fi
  if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
    echo "DIED lfm-0.28"
    grep -E "Error|ValueError|not support|architecture" "${ROOT}/logs/vllm-alt-lfm-028.log" | tail -20 | tee "${ROOT}/raw/alt-lfm-028-error.txt"
    break
  fi
  sleep 2
done
if [[ "${lfm_ok}" == 1 ]]; then
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${LFM_MODEL}" --hf-id "${LFM_MODEL}" \
    --quantization FP8 --engine vllm --engine-version 0.28.0 \
    --profiles A --concurrencies 1,8,16 --mode sustained --duration 60 --warmup 1 \
    --tag lfm25-fp8 --context-configured 131072 --kv-cache fp8 \
    --attention auto --moe-backend auto --mtp off --draft-tokens 0 --thinking off \
    || echo "lfm A failed"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${LFM_MODEL}" --hf-id "${LFM_MODEL}" \
    --quantization FP8 --engine vllm --engine-version 0.28.0 \
    --profiles B --concurrencies 8,16 --mode sustained --duration 60 --warmup 1 \
    --tag lfm25-fp8 --context-configured 131072 --kv-cache fp8 \
    --attention auto --moe-backend auto --mtp off --draft-tokens 0 --thinking off \
    || echo "lfm B failed"
  LFM_A16=$(agg_of "lfm25-fp8-A-c16")
  echo "LFM_A16 ${LFM_A16}"
  awk -v a="${LFM_A16:-0}" 'BEGIN{exit !(a+0 >= 400)}' && {
    python3 "${ROOT}/scripts/long_concurrency.py" --model "${LFM_MODEL}" \
      --mtp lfm25-fp8 --draft-tokens 0 --concurrency 1 --target-tokens 118000 \
      --min-tokens 1024 --max-tokens 1024 || echo "lfm long failed"
    python3 "${ROOT}/scripts/quality_hard.py" --model "${LFM_MODEL}" --tag lfm25-fp8 --thinking off --engine vllm --max-tokens 4096 \
      || echo "lfm quality failed"
  } || echo "LFM not competitive enough for long-context and quality"
else
  record_fail "lfm25-fp8-startup-$(date -u +%Y%m%dT%H%M%SZ)" "${LFM_MODEL}" '{"engine":"vllm 0.28.0","note":"FP8 checkpoint did not stay up; newer vLLM was not pulled after this single attempt"}'
fi
stop_all
echo "ALT DONE $(date -Is)"
