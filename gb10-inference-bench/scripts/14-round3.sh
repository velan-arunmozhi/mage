#!/bin/bash
# Short-context saturation, long-context decode, then coding quality.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/14-round3.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "ROUND3 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
free -h

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
  if [[ ! -s "${IMG}" ]]; then
    cp "${VLLM_SIF}" "${IMG}"
  fi
  apptainer exec --nv "${IMG}" vllm --version
  if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
    echo "copying Qwen weights $(date -Is)"
    mkdir -p "${QWEN_LOCAL}"
    cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
  fi
  du -sh "${QWEN_LOCAL}"
}

launch_qwen() {
  local name="$1" spec="$2" seqs="$3" util="$4"
  stop_all
  echo "LAUNCH ${name} seqs=${seqs} util=${util} $(date -Is)"
  free -h
  local -a spec_args=()
  if [[ -n "${spec}" ]]; then
    spec_args=(--speculative-config "${spec}")
  fi
  printf '%s\n' "name=${name} seqs=${seqs} util=${util} spec=${spec}" > "${ROOT}/configs/round3-${name}.cmd"
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
      > "${ROOT}/logs/vllm-round3-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      grep -E "KV cache size|Model loading took|Maximum concurrency" "${ROOT}/logs/vllm-round3-${name}.log" | tee "${ROOT}/raw/round3-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "ValueError|No available|Free memory" "${ROOT}/logs/vllm-round3-${name}.log" | tail -6 | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then echo "waiting ${name} ${i}"; tail -1 "${ROOT}/logs/vllm-round3-${name}.log" || true; fi
    sleep 2
  done
  echo "TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  stop_all
  return 1
}

bench_a() {
  local tag="$1" concs="$2" drafts="$3"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" --model "${QWEN_MODEL}" --hf-id "${QWEN_MODEL}" \
    --quantization NVFP4 --engine vllm --engine-version "vllm 0.28.0 cuda-graphs round3" \
    --profiles A --concurrencies "${concs}" --mode sustained --duration 60 --warmup 1 \
    --timeout 1800 --tag "${tag}" --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend marlin --mtp mtp --draft-tokens "${drafts}" \
    --thinking off --raw-dir "${ROOT}/raw"
}

agg_of() {
  python3 - << PY
import csv
rows=list(csv.DictReader(open("${ROOT}/results.csv")))
val=""
for r in rows:
    if r.get("experiment_id","").startswith("${1}") and r.get("profile")=="A" and str(r.get("concurrency_requested"))=="${2}":
        val=r.get("aggregate_tok_s") or ""
print(val)
PY
}

long_pair() {
  local mtp="$1" drafts="$2"
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp "${mtp}" --draft-tokens "${drafts}" --concurrency 1 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024 || echo "long ${mtp} c1 failed" | tee -a "${ROOT}/failures.md"
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp "${mtp}" --draft-tokens "${drafts}" --concurrency 4 --target-tokens 118000 --min-tokens 1024 --max-tokens 1024 || echo "long ${mtp} c4 failed" | tee -a "${ROOT}/failures.md"
}

prepare
SPEC3='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
if ! launch_qwen mtp3-u45-s32 "${SPEC3}" 32 0.45; then
  echo "32-seq at 0.45 failed; retry 0.50" | tee -a "${ROOT}/failures.md"
  launch_qwen mtp3-u50-s32 "${SPEC3}" 32 0.50 || { echo "MTP3 saturation server failed" | tee -a "${ROOT}/failures.md"; exit 1; }
fi
bench_a qwen36-mtp3-r3 32 3 || echo "c32 bench failed" | tee -a "${ROOT}/failures.md"
a32=$(agg_of qwen36-mtp3-r3 32)
echo "A32=${a32} baseline24=580.75"
go_higher=$(python3 - << PY
a32=float("${a32:-0}" or 0)
print("YES" if a32 >= 580.75 * 1.05 else "NO")
PY
)
echo "higher=${go_higher}"
if [[ "${go_higher}" == "YES" ]]; then
  stop_all
  if launch_qwen mtp3-u45-s48 "${SPEC3}" 48 0.45; then
    bench_a qwen36-mtp3-r3 40 3 || true
    a40=$(agg_of qwen36-mtp3-r3 40)
    echo "A40=${a40}"
    if python3 - << PY
a40=float("${a40:-0}" or 0); a32=float("${a32:-0}" or 0)
raise SystemExit(0 if a32 and a40 >= a32 * 1.05 else 1)
PY
    then
      bench_a qwen36-mtp3-r3 48 3 || true
    else
      echo "40 did not beat 32 by 5%; stopping the sweep"
    fi
  else
    echo "48-seq server failed; saturation sweep stops at 32" | tee -a "${ROOT}/failures.md"
  fi
fi

echo "LONG DECODE MTP3 $(date -Is)"
if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  long_pair mtp3 3
else
  launch_qwen mtp3-long "${SPEC3}" 4 0.45 && long_pair mtp3 3
fi
python3 "${ROOT}/scripts/quality_round3.py" --model "${QWEN_MODEL}" --tag qwen36-mtp3 --thinking server-default --engine vllm --max-tokens 4096 || echo "qwen quality failed" | tee -a "${ROOT}/failures.md"
stop_all

echo "LONG DECODE MTP0 $(date -Is)"
if launch_qwen mtp0-long "" 4 0.45; then
  long_pair mtp0 0
fi
stop_all

echo "QUALITY 2B $(date -Is)"
llama_env
"${LLAMA_SERVER}" -m "${QWEN35_2B_GGUF}" --alias qwen35-2b --host 127.0.0.1 --port 8080 \
  -ngl 999 -fa on -c 32768 -np 1 -t 20 --jinja --reasoning off --metrics \
  > "${ROOT}/logs/llama-2b-quality.log" 2>&1 &
echo $! > "${ROOT}/state/llama.pid"
ready=0
for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:8080/health >/dev/null; then ready=1; break; fi
  sleep 2
done
if [[ "${ready}" == 1 ]]; then
  python3 "${ROOT}/scripts/quality_round3.py" --base-url http://127.0.0.1:8080 --model qwen35-2b --tag qwen35-2b --thinking off --engine llama.cpp --max-tokens 4096 || echo "2b quality failed" | tee -a "${ROOT}/failures.md"
else
  echo "2b server failed" | tee -a "${ROOT}/failures.md"
fi
stop_all
echo "ROUND3 DONE $(date -Is)"
