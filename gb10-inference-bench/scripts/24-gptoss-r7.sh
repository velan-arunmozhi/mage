#!/bin/bash
# GPT-OSS higher concurrency after the free-memory snapshot is stable.
set -u
source /scratch/scholar/billin19/gb10-inference-bench/scripts/common.sh
cd "${ROOT}"
export BENCH_ROOT="${ROOT}"
IMG=/tmp/vllm-apptainer/vllm-openai-0.28.0.sif
PORT=8000
GPT_ID="openai/gpt-oss-20b"
GPT_LOCAL=/tmp/models/gpt-oss-20b
LOG="${ROOT}/logs/24-gptoss-r7.out"
mkdir -p /tmp/vllm-apptainer /tmp/models "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs"
exec > >(tee -a "${LOG}") 2>&1
echo "R7 START $(date -Is) job=${SLURM_JOB_ID:-} host=$(hostname)"

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

cuda_free() {
  apptainer exec --nv "${IMG}" python3 -c 'import torch; f,t=torch.cuda.mem_get_info(); print(int(f), int(t))'
}

stabilize() {
  python3 - <<'PY' >&2
n = 40 * 1024**3
buf = bytearray(n)
for i in range(0, n, 4 * 1024 * 1024):
    buf[i] = 1
del buf
print("EVICTED")
PY
  local prev now total i
  read -r prev total < <(cuda_free)
  echo "FREE_SAMPLE 0 ${prev} ${total}" >&2
  for i in 1 2 3 4; do
    sleep 5
    read -r now total < <(cuda_free)
    echo "FREE_SAMPLE ${i} ${now} ${total}" >&2
    python3 -c 'import sys; a=int(sys.argv[1]); b=int(sys.argv[2]); sys.exit(0 if abs(a-b) < 2*1024**3 else 1)' "${prev}" "${now}" && break
    prev=${now}
  done
  python3 -c 'free=int("'"${now}"'"); total=int("'"${total}"'"); print(f"{min(0.42, (free / total) * 0.65):.2f}")'
}

if [[ ! -s "${IMG}" ]]; then cp "${VLLM_SIF}" "${IMG}"; fi
if [[ ! -f "${GPT_LOCAL}/config.json" ]]; then
  snap=$(find "${HF_HOME}/hub/models--openai--gpt-oss-20b/snapshots" -mindepth 2 -maxdepth 2 -name config.json -printf '%h\n' | head -1)
  if [[ -z "${snap}" || ! -f "${snap}/config.json" ]]; then echo "GPT weights missing"; exit 1; fi
  mkdir -p "${GPT_LOCAL}"
  echo "COPY ${snap}"
  cp -aL "${snap}/." "${GPT_LOCAL}/"
fi

launch() {
  local name="$1" seqs="$2" extra="$3"
  stop_all
  local util
  util=$(stabilize)
  echo "LAUNCH ${name} seqs=${seqs} util=${util} extra=${extra}"
  printf '%s\n' "seqs=${seqs} util=${util} ${extra} graphs=on kv=fp8 attention=flashinfer" > "${ROOT}/configs/r7-${name}.cmd"
  # shellcheck disable=SC2086
  apptainer exec --nv \
    --bind "${HF_HOME}:/root/.cache/huggingface" \
    --bind "${ROOT}/vllm-cache:/root/.cache/vllm" \
    --bind "${ROOT}/tmp:/tmp" \
    --bind /tmp/models:/tmp/models \
    --bind "${ROOT}/encodings:/encodings:ro" \
    --env HF_HOME=/root/.cache/huggingface \
    --env PYTHONUNBUFFERED=1 \
    --env VLLM_CACHE_ROOT=/root/.cache/vllm \
    --env PYTORCH_CUDA_ALLOC_CONF=backend:native \
    --env TIKTOKEN_ENCODINGS_BASE=/encodings \
    "${IMG}" vllm serve "${GPT_LOCAL}" \
      --served-model-name "${GPT_ID}" \
      --host 127.0.0.1 --port "${PORT}" --tensor-parallel-size 1 --trust-remote-code \
      --max-model-len 131072 --max-num-seqs "${seqs}" --max-num-batched-tokens 8192 \
      --gpu-memory-utilization "${util}" --kv-cache-dtype fp8 \
      --attention-backend flashinfer \
      --enable-chunked-prefill --enable-prefix-caching \
      --safetensors-load-strategy eager \
      --tool-call-parser openai --enable-auto-tool-choice \
      ${extra} \
      > "${ROOT}/logs/vllm-r7-${name}.log" 2>&1 &
  echo $! > "${ROOT}/state/vllm.pid"
  local i
  for i in $(seq 1 700); do
    if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
      echo "READY ${name}"
      grep -E "KV cache size|Available KV|consumed memory|CUDA graph|Model loading took|Free memory on device" "${ROOT}/logs/vllm-r7-${name}.log" | tee "${ROOT}/raw/r7-${name}-kv.txt" || true
      return 0
    fi
    if ! kill -0 "$(cat "${ROOT}/state/vllm.pid")" 2>/dev/null; then
      echo "DIED ${name}"
      grep -E "AssertionError|ValueError|illegal|Free memory|No available|unrecognized" "${ROOT}/logs/vllm-r7-${name}.log" | tail -8 | tee "${ROOT}/raw/r7-${name}-error.txt"
      return 1
    fi
    sleep 2
  done
  return 1
}

bench() {
  local profile="$1" concs="$2"
  python3 "${ROOT}/scripts/bench_client.py" \
    --base-url "http://127.0.0.1:${PORT}" --model "${GPT_ID}" --hf-id "${GPT_ID}" \
    --quantization MXFP4 --engine vllm --engine-version 0.28.0 \
    --profiles "${profile}" --concurrencies "${concs}" --mode sustained --duration 60 --warmup 1 \
    --tag gptoss-r7 --context-configured 131072 --kv-cache fp8 \
    --attention flashinfer --moe-backend default --mtp off --draft-tokens 0 \
    --thinking low || echo "bench ${profile} ${concs} failed"
}

agg_run() {
  local conc="$1"
  python3 - <<PY
import json
last=None
for line in open("${ROOT}/results.jsonl"):
    row=json.loads(line)
    if row.get("experiment_id","").startswith("gptoss-r7-A-c${conc}-"):
        last=row
if not last:
    print("0 0 0")
else:
    notes=json.loads(last.get("notes") or "{}")
    print(last.get("aggregate_tok_s") or 0, last.get("engine_running_max") or 0, notes.get("engine_waiting_max") or 0, last.get("ttft_p50_s") or 0)
PY
}

if ! launch s96 96 ""; then
  echo "retry 96 with an explicit 20 GiB KV budget"
  launch s96-kv 96 "--kv-cache-memory 21474836480" || true
fi
if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  echo "GPT96_FAILED"
  exit 1
fi
bench A 96
read -r AGG RUN WAIT TTFT < <(agg_run 96)
echo "A96 agg=${AGG} run=${RUN} wait=${WAIT} ttft=${TTFT}"
RISE=$(python3 -c 'import sys; agg=float(sys.argv[1]); run=float(sys.argv[2]); wait=float(sys.argv[3]); ttft=float(sys.argv[4]); print("yes" if agg>1013*1.03 and run>=90 and wait<40 and ttft<15 else "no")' "${AGG}" "${RUN}" "${WAIT}" "${TTFT}")
echo "RISE96 ${RISE}"
if [[ "${RISE}" == yes ]]; then
  if launch s128 128 ""; then
    bench A 128
  else
    echo "128 failed; restoring 96 for the 8k and quality runs"
    launch s96b 96 "" || launch s96b-kv 96 "--kv-cache-memory 21474836480" || true
  fi
fi
if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
  bench B 48,64
  python3 "${ROOT}/scripts/quality_hard.py" --model "${GPT_ID}" --tag gptoss-low --thinking low --engine vllm --max-tokens 4096 \
    || echo "quality low failed"
  qline=$(grep "QUALITY gptoss-low " "${LOG}" | tail -1 || true)
  echo "QUALITY_LINE ${qline}"
  passes=$(printf '%s\n' "${qline}" | sed -n 's/.* \([0-9][0-9]*\)\/10.*/\1/p')
  if [[ "${passes:-0}" -ge 7 ]]; then
  python3 - <<PY
import json, sys, threading, time
sys.path.insert(0, "${ROOT}/scripts")
from quality_hard import TASKS
from quality_round2 import check, extract_json
from quality_round3 import chat
from record import record
from datetime import datetime, timezone
base="http://127.0.0.1:8000"
model="openai/gpt-oss-20b"
results=[]
lock=threading.Lock()
def run(task):
    started=time.perf_counter()
    try:
        result=chat(base, model, task["prompt"], 4096, "low")
        text=result["text"]
        if task["check"]=="json-exact":
            obj=extract_json(text)
            ok=obj==task["expect"]
        else:
            ok, _=check(task, text)
        usage=result.get("usage") or {}
    except Exception as exc:
        ok, usage, result=False, {}, {"elapsed_s": time.perf_counter()-started}
        print(f"MIX {task['name']} ERR {type(exc).__name__}", flush=True)
    elapsed=float(result.get("elapsed_s") or 0)
    with lock:
        results.append((task["name"], bool(ok), int((usage or {}).get("completion_tokens") or 0), elapsed))
        print(f"MIX {task['name']} ok={ok} t={elapsed:.1f}", flush=True)
threads=[threading.Thread(target=run, args=(task,)) for task in TASKS]
wall=time.perf_counter()
# Four at a time, same tasks, natural completions.
for i in range(0, len(threads), 4):
    batch=threads[i:i+4]
    for thread in batch:
        thread.start()
    for thread in batch:
        thread.join()
wall=time.perf_counter()-wall
passed=sum(1 for _, ok, _, _ in results if ok)
record({
    "experiment_id": f"quality4-gptoss-low-mix-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": "ok",
    "model": model,
    "hf_id": model,
    "quantization": "MXFP4",
    "engine": "vllm",
    "engine_version": "0.28.0",
    "profile": "quality-hard-10-concurrent4",
    "concurrency_requested": 4,
    "mode": "quality",
    "mtp": "low",
    "output_tokens_actual": sum(tok for _, _, tok, _ in results),
    "duration_s": wall,
    "completed": passed,
    "failed": len(TASKS)-passed,
    "notes": json.dumps({"thinking": "low", "passed": passed, "wall_s": wall, "tasks_per_minute": (passed/wall*60) if wall else None, "tasks": [f"{n}:{ok}" for n, ok, _, _ in results]}),
})
print(f"MIXED {passed}/10 wall={wall:.1f}s", flush=True)
PY
  fi
  python3 "${ROOT}/scripts/long_concurrency.py" --model "${GPT_ID}" \
    --mtp gptoss-low-c2 --draft-tokens 0 --concurrency 2 --target-tokens 118000 \
    --min-tokens 1024 --max-tokens 1024 --system "Reasoning: low" || echo "long c2 failed"
fi
stop_all
echo "R7 DONE $(date -Is)"
