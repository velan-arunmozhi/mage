#!/bin/bash
# Round 2: MTP3 scaling, profile B, filled long context, quality, optional Ornith MTP.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
QWEN_MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"
QWEN_LOCAL=/tmp/models/qwen36-nvfp4
SNAP="${HF_HOME}/hub/models--nvidia--Qwen3.6-35B-A3B-NVFP4/snapshots/1355db6a052410cfd62085d94b58866fd0f2c3c5"
LOG="${ROOT}/logs/12-round2.out"

mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "ROUND2 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"
free -h

stop_all() {
  if [[ -f "${ROOT}/state/vllm.pid" ]]; then
    kill -9 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/vllm.pid"
  fi
  ps -eo pid,comm | awk '$2 ~ /EngineCor/ {print $1}' | while read -r pid; do
    kill -9 "${pid}" 2>/dev/null || true
  done
  sleep 4
}

prepare() {
  if [[ ! -s "${IMG}" ]]; then
    echo "copying sif to node nvme"
    cp -n "${VLLM_SIF}" "${IMG}"
  fi
  if ! apptainer exec --nv "${IMG}" vllm --version; then
    echo "sif unusable, pulling vllm 0.28.0" | tee -a "${ROOT}/failures.md"
    export APPTAINER_CACHEDIR=/tmp/vllm-apptainer/cache
    export APPTAINER_TMPDIR=/tmp/vllm-apptainer/tmp
    mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"
    apptainer pull "${IMG}" docker://vllm/vllm-openai:v0.28.0
  fi
  if [[ ! -f "${QWEN_LOCAL}/config.json" ]]; then
    echo "copying Qwen weights to nvme $(date -Is)"
    mkdir -p "${QWEN_LOCAL}"
    cp -aL "${SNAP}/." "${QWEN_LOCAL}/"
  fi
  du -sh "${QWEN_LOCAL}" "${IMG}"
}

launch_qwen() {
  local name="$1" spec="$2" seqs="$3" util="${4:-0.40}"
  stop_all
  echo "LAUNCH ${name} seqs=${seqs} $(date -Is)"
  free -h
  local -a spec_args=()
  if [[ -n "${spec}" ]]; then
    spec_args=(--speculative-config "${spec}")
  fi
  {
    echo "name=${name} seqs=${seqs} spec=${spec}"
  } > "${ROOT}/configs/round2-${name}.cmd"
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
      --max-model-len 131072 \
      --max-num-seqs "${seqs}" \
      --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" \
      --kv-cache-dtype fp8 \
      --attention-backend flashinfer \
      --moe-backend marlin \
      --enable-chunked-prefill \
      --enable-prefix-caching \
      --safetensors-load-strategy eager \
      --reasoning-parser qwen3 \
      ${spec_args[@]+"${spec_args[@]}"} \
      > "${ROOT}/logs/vllm-round2-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 900); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name} after $((i * 2))s"
      grep -E "KV cache size|Model loading took|Maximum concurrency" "${ROOT}/logs/vllm-round2-${name}.log" | tee "${ROOT}/raw/round2-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      tail -40 "${ROOT}/logs/vllm-round2-${name}.log" | tee -a "${ROOT}/failures.md"
      return 1
    fi
    if (( i % 20 == 0 )); then
      echo "waiting ${name} ${i}"
      tail -1 "${ROOT}/logs/vllm-round2-${name}.log" || true
    fi
    sleep 2
  done
  echo "TIMEOUT ${name}" | tee -a "${ROOT}/failures.md"
  stop_all
  return 1
}

bench() {
  local tag="$1" profiles="$2" concs="$3" mtp="$4" drafts="$5"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" \
    --model "${QWEN_MODEL}" \
    --hf-id "${QWEN_MODEL}" \
    --quantization NVFP4 \
    --engine vllm \
    --engine-version "vllm 0.28.0 cuda-graphs round2" \
    --profiles "${profiles}" \
    --concurrencies "${concs}" \
    --mode sustained \
    --duration 60 \
    --warmup 1 \
    --timeout 1800 \
    --tag "${tag}" \
    --context-configured 131072 \
    --kv-cache fp8 \
    --attention flashinfer \
    --moe-backend marlin \
    --mtp "${mtp}" \
    --draft-tokens "${drafts}" \
    --thinking off \
    --raw-dir "${ROOT}/raw"
}

agg_of() {
  local profile="$1" conc="$2"
  python3 - << PY
import csv
rows=list(csv.DictReader(open("${ROOT}/results.csv")))
want_p, want_c = "${profile}", "${conc}"
val=None
for r in rows:
        if r.get("profile")==want_p and str(r.get("concurrency_requested"))==want_c and "qwen36-mtp3-r2" in r.get("experiment_id",""):
        val=r.get("aggregate_tok_s")
print(val or "")
PY
}

minutes_left() {
  local left
  left=$(squeue -h -j "${SLURM_JOB_ID}" -o %L 2>/dev/null || echo 0)
  python3 -c 'import os; t=os.environ.get("L","0"); p=[int(x) for x in t.split(":") if x!=""];
print((p[0]*60+p[1]) if len(p)==3 else (p[0] if p else 0))' 
}

prepare

SPEC3='{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
# max-num-seqs 24 at utilization 0.26 left no KV. Use 0.40 on a clean node and 16 active sequences.
if ! launch_qwen mtp3-s16 "${SPEC3}" 16 0.40; then
  echo "MTP3 at 0.40 failed; retrying 0.32" | tee -a "${ROOT}/failures.md"
  launch_qwen mtp3-s16 "${SPEC3}" 16 0.32 || true
fi
if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  bench qwen36-mtp3-r2 A "8,12,16" mtp 3 || echo "profile A bench failed" | tee -a "${ROOT}/failures.md"
  a12=$(agg_of A 12)
  a16=$(agg_of A 16)
  echo "A12=${a12} A16=${a16}"
  decision=$(python3 - << PY
a12=float("${a12:-0}" or 0)
a16=float("${a16:-0}" or 0)
print("RUN24" if a12 and a16 >= a12 * 1.05 else "STOP24")
PY
)
  echo "decision ${decision}"
  if [[ "${decision}" == "RUN24" ]]; then
    echo "throughput still rising; relaunching with 24 sequences"
    launch_qwen mtp3-s24 "${SPEC3}" 24 0.40 || true
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      bench qwen36-mtp3-r2 A 24 mtp 3 || true
    fi
  fi
  bench qwen36-mtp3-r2 B "4,8,12,16" mtp 3 || echo "profile B bench failed" | tee -a "${ROOT}/failures.md"
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp3 --draft-tokens 3 --concurrency 2 --max-tokens 512 || echo "long mtp3 c2 failed" | tee -a "${ROOT}/failures.md"
  if grep -q "LONG mtp3 c=2 completed=2 failed=0 retrieved=2" "${LOG}"; then
    python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp3 --draft-tokens 3 --concurrency 4 --max-tokens 512 || echo "long mtp3 c4 failed" | tee -a "${ROOT}/failures.md"
  else
    echo "skip mtp3 4-way long context; 2-way was not fully successful" | tee -a "${ROOT}/failures.md"
  fi
  python3 "${ROOT}/scripts/quality_round2.py" || echo "quality failed" | tee -a "${ROOT}/failures.md"
else
  echo "MTP3 server failed" | tee -a "${ROOT}/failures.md"
fi
stop_all

if launch_qwen mtp0-s8 "" 8; then
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp0 --draft-tokens 0 --concurrency 2 --max-tokens 512 || echo "long mtp0 c2 failed" | tee -a "${ROOT}/failures.md"
  if grep -q "LONG mtp0 c=2 completed=2 failed=0 retrieved=2" "${LOG}"; then
    python3 "${ROOT}/scripts/long_concurrency.py" --model "${QWEN_MODEL}" --mtp mtp0 --draft-tokens 0 --concurrency 4 --max-tokens 512 || echo "long mtp0 c4 failed" | tee -a "${ROOT}/failures.md"
  fi
fi
stop_all

left=$(L="$(squeue -h -j "${SLURM_JOB_ID}" -o %L 2>/dev/null || echo 0)" python3 -c 'import os; t=os.environ.get("L","0"); p=[int(x) for x in t.split(":") if x!=""]; print((p[0]*60+p[1]) if len(p)==3 else (p[0] if p else 0))')
echo "minutes left ${left}"
if [[ "${left}" -ge 45 ]]; then
  echo "starting optional Ornith MTP"
  bash "${ROOT}/scripts/09-ornith-mtp.sh" || echo "ornith mtp failed" | tee -a "${ROOT}/failures.md"
else
  echo "skipping Ornith MTP; ${left} minutes left" | tee -a "${ROOT}/failures.md"
fi
stop_all
echo "ROUND2 DONE $(date -Is)"
