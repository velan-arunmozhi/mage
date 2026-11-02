#!/bin/bash
# Stage 0: llama.cpp baselines for cached Qwen3.5-2B and Qwen3.6 GGUF.
# Failures of one command do not stop the rest.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
llama_env
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
VER="$("${LLAMA_BENCH}" --version 2>&1 | head -5 | tr '\n' ' ')"
echo "llama version: ${VER}"

mem_watch() {
  local name="$1"
  local file="${ROOT}/logs/mem-${name}.log"
  (
    while true; do
      date -Is
      nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || true
      awk '/MemAvailable|MemTotal|MemFree/ {print}' /proc/meminfo
      sleep 5
    done
  ) > "${file}" 2>&1 &
  echo $! > "${ROOT}/state/memwatch.pid"
}

stop_mem_watch() {
  if [[ -f "${ROOT}/state/memwatch.pid" ]]; then
    kill "$(cat "${ROOT}/state/memwatch.pid")" 2>/dev/null || true
    rm -f "${ROOT}/state/memwatch.pid"
  fi
}

run_cmd() {
  local name="$1"
  shift
  local out="${ROOT}/raw/${name}.jsonl"
  local err="${ROOT}/raw/${name}.err"
  echo "BEGIN ${name} $(date -Is)"
  echo "CMD: $*" | tee "${ROOT}/configs/${name}.cmd"
  mem_watch "${name}"
  timeout 1800 "$@" > "${out}" 2> "${err}"
  local ec=$?
  stop_mem_watch
  echo "END ${name} exit=${ec} $(date -Is)"
  echo "${ec}" > "${ROOT}/raw/${name}.exit"
  if [[ "${ec}" -ne 0 ]]; then
    echo "FAILED ${name} exit ${ec}" >> "${ROOT}/failures.md"
    tail -30 "${err}" >> "${ROOT}/failures.md" || true
  fi
  return 0
}

ingest_bench() {
  local file="$1" model="$2" hf="$3" quant="$4"
  python3 "${ROOT}/scripts/ingest_llama_bench.py" --kind bench --path "${file}" \
    --model "${model}" --hf-id "${hf}" --quant "${quant}" --engine-version "${VER}" || true
}

ingest_batch() {
  local file="$1" model="$2" hf="$3" quant="$4" ctx="$5"
  python3 "${ROOT}/scripts/ingest_llama_bench.py" --kind batched --path "${file}" \
    --model "${model}" --hf-id "${hf}" --quant "${quant}" --engine-version "${VER}" --context "${ctx}" || true
}

# --- isolated pp/tg ---
run_cmd qwen35-2b-short "${LLAMA_BENCH}" -m "${QWEN35_2B_GGUF}" -ngl 999 -fa on -t 20 -r 2 --progress -o jsonl \
  -pg 1024,512 -pg 8192,256
ingest_bench "${ROOT}/raw/qwen35-2b-short.jsonl" "Qwen3.5-2B" "unsloth/Qwen3.5-2B-GGUF" "Q4_K_M"

run_cmd qwen35-2b-32k "${LLAMA_BENCH}" -m "${QWEN35_2B_GGUF}" -ngl 999 -fa on -t 20 -r 1 --progress -o jsonl \
  -pg 32768,128
ingest_bench "${ROOT}/raw/qwen35-2b-32k.jsonl" "Qwen3.5-2B" "unsloth/Qwen3.5-2B-GGUF" "Q4_K_M"

run_cmd qwen36-short "${LLAMA_BENCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa on -t 20 -r 2 --progress -o jsonl \
  -pg 1024,512 -pg 8192,256
ingest_bench "${ROOT}/raw/qwen36-short.jsonl" "Qwen3.6-35B-A3B" "unsloth/Qwen3.6-35B-A3B-GGUF" "UD-Q4_K_M"

run_cmd qwen36-32k "${LLAMA_BENCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa on -t 20 -r 1 --progress -o jsonl \
  -pg 32768,128
ingest_bench "${ROOT}/raw/qwen36-32k.jsonl" "Qwen3.6-35B-A3B" "unsloth/Qwen3.6-35B-A3B-GGUF" "UD-Q4_K_M"

run_cmd qwen36-depth32k "${LLAMA_BENCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa on -t 20 -r 1 --progress -o jsonl \
  -p 128 -n 128 -d 32768
ingest_bench "${ROOT}/raw/qwen36-depth32k.jsonl" "Qwen3.6-35B-A3B" "unsloth/Qwen3.6-35B-A3B-GGUF" "UD-Q4_K_M"

run_cmd qwen35-2b-depth120k "${LLAMA_BENCH}" -m "${QWEN35_2B_GGUF}" -ngl 999 -fa on -t 20 -r 1 --progress -o jsonl \
  -p 256 -n 128 -d 120000
ingest_bench "${ROOT}/raw/qwen35-2b-depth120k.jsonl" "Qwen3.5-2B" "unsloth/Qwen3.5-2B-GGUF" "Q4_K_M"

# --- concurrent decode, unified KV pool ---
run_cmd qwen35-2b-batch "${LLAMA_BATCH}" -m "${QWEN35_2B_GGUF}" -ngl 999 -fa on -kvu -c 131072 -b 4096 -ub 1024 -t 20 \
  --output-format jsonl -npp 1024,8192 -ntg 256 -npl 1,2,4,8,12,16
ingest_batch "${ROOT}/raw/qwen35-2b-batch.jsonl" "Qwen3.5-2B" "unsloth/Qwen3.5-2B-GGUF" "Q4_K_M" 131072

run_cmd qwen36-batch "${LLAMA_BATCH}" -m "${QWEN36_GGUF}" -ngl 999 -fa on -kvu -c 131072 -b 4096 -ub 1024 -t 20 \
  --output-format jsonl -npp 1024,8192 -ntg 256 -npl 1,2,4,8,12,16
ingest_batch "${ROOT}/raw/qwen36-batch.jsonl" "Qwen3.6-35B-A3B" "unsloth/Qwen3.6-35B-A3B-GGUF" "UD-Q4_K_M" 131072

stop_server() {
  if [[ -f "${ROOT}/state/llama-server.pid" ]]; then
    local pid
    pid="$(cat "${ROOT}/state/llama-server.pid")"
    kill "${pid}" 2>/dev/null || true
    sleep 3
    kill -9 "${pid}" 2>/dev/null || true
    rm -f "${ROOT}/state/llama-server.pid"
  fi
  sleep 2
}

start_server() {
  local model="$1" alias="$2" ctx="$3" np="$4" logname="$5"
  stop_server
  local log="${ROOT}/logs/${logname}.log"
  echo "START SERVER ${alias} ctx=${ctx} np=${np}"
  "${LLAMA_SERVER}" \
    -m "${model}" \
    --alias "${alias}" \
    --host 127.0.0.1 \
    --port 8080 \
    -ngl 999 \
    -fa on \
    -c "${ctx}" \
    -np "${np}" \
    -kvu \
    -t 20 \
    -b 4096 \
    -ub 1024 \
    --jinja \
    --reasoning off \
    --metrics \
    > "${log}" 2>&1 &
  echo $! > "${ROOT}/state/llama-server.pid"
  local i
  for i in $(seq 1 600); do
    if curl -sf http://127.0.0.1:8080/health >/dev/null; then
      echo "SERVER READY ${alias} after ${i} checks"
      grep -E "n_ctx|kv_unified|flash_attn|listening" "${log}" | head -40 || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/llama-server.pid")" 2>/dev/null; then
      echo "SERVER DIED ${alias}"
      tail -40 "${log}"
      return 1
    fi
    sleep 2
  done
  echo "SERVER TIMEOUT ${alias}"
  return 1
}

serve_bench() {
  local model="$1" alias="$2" hf="$3" quant="$4" ctx="$5"
  if ! start_server "${model}" "${alias}" "${ctx}" 16 "server-${alias}"; then
    echo "SKIP serve bench ${alias}" >> "${ROOT}/failures.md"
    stop_server
    return 0
  fi
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url http://127.0.0.1:8080 \
    --model "${alias}" \
    --hf-id "${hf}" \
    --quantization "${quant}" \
    --engine llama.cpp \
    --engine-version "${VER}" \
    --profiles A,B \
    --concurrencies 1,2,4,8,12,16 \
    --mode sustained \
    --duration 60 \
    --warmup 1 \
    --timeout 900 \
    --tag "llama-${alias}-c${ctx}" \
    --context-configured "${ctx}" \
    --kv-cache "unified-default" \
    --attention flash-attn \
    --mtp off \
    --thinking off \
    --raw-dir "${ROOT}/raw" || echo "bench_client failed for ${alias}" >> "${ROOT}/failures.md"
  stop_server
}

serve_bench "${QWEN35_2B_GGUF}" "qwen35-2b" "unsloth/Qwen3.5-2B-GGUF" "Q4_K_M" 131072
serve_bench "${QWEN36_GGUF}" "qwen36-udq4" "unsloth/Qwen3.6-35B-A3B-GGUF" "UD-Q4_K_M" 131072

echo "BASELINE COMPLETE $(date -Is)"
