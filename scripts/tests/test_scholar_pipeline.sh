#!/usr/bin/env bash
# Mocked checks for the Scholar launcher. This file does not allocate a GPU,
# submit a SLURM job, download weights, or start llama-server.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="${ROOT}/scripts/lib/mage-scholar.sh"
SESSION="${ROOT}/scripts/scholar-session"
EVAL="${ROOT}/scripts/eval-host"
PY="${ROOT}/scripts/lib/mage_scholar.py"

unset MAGE_MODEL_PROFILE MAGE_MODEL_HF MAGE_MODEL_FILE MAGE_MODEL_ALIAS MAGE_MODEL_REVISION \
  MAGE_CONTEXT MAGE_GPU_LAYERS MAGE_FLASH_ATTN MAGE_PARALLEL MAGE_PORT MAGE_BIND \
  MAGE_CUDA_MANAGED MAGE_OUTPUT_LIMIT MAGE_SMOKE_MAX_TOKENS MAGE_REASONING \
  MAGE_TEMPERATURE MAGE_LLAMA_EXTRA MAGE_SCRATCH MAGE_LLAMA_SRC MAGE_LLAMA_BIN \
  GGML_CUDA_ENABLE_UNIFIED_MEMORY CUDA_ROOT MAGE_CUDA_ROOT MAGE_GPU_NAME \
  MAGE_SKIP_MODULES MAGE_DISABLE_LDCONFIG MAGE_KILL_LOG MAGE_PROC_ROOT \
  MAGE_HOSTNAME SLURM_JOB_ID MAGE_RUN_ID MAGE_RUN_DIR || true

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

py() {
  if command -v python3 >/dev/null 2>&1; then
    python3 "$@"
  else
    python "$@"
  fi
}

assert_eq() {
  local got="$1"
  local want="$2"
  local label="$3"
  [[ "$got" == "$want" ]] || fail "${label}: got [${got}] want [${want}]"
}

bash -n "$LIB"
bash -n "$SESSION"
bash -n "$EVAL"
bash -n "$0"

# shellcheck source=../lib/mage-scholar.sh
source "$LIB"

help_out="$(bash "$SESSION" --help)"
grep -q "qwen36-35b" <<< "$help_out" || fail "scholar-session help lacks the pilot profile"
bash "$SESSION" help >/dev/null
bash "$EVAL" --help >/dev/null
bash "$EVAL" help >/dev/null

plan="$(bash "$SESSION" plan --model-profile qwen36-35b)"
grep -q "unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M" <<< "$plan" || fail "plan omitted the Qwen3.6 reference"
grep -q "131072" <<< "$plan" || fail "plan omitted 131072 context"
grep -q -- "-fa off" <<< "$plan" || fail "plan did not keep Flash Attention off for qwen36"
grep -q "Dry run" <<< "$plan" || fail "plan did not say it was a dry run"

custom="$(bash "$SESSION" plan --model-hf org/Custom-GGUF:Q4_K_M --model-alias custom --context 2048 --output-limit 256 --smoke-max-tokens 64)"
grep -q "org/Custom-GGUF:Q4_K_M" <<< "$custom" || fail "custom model did not reach the plan"
grep -q -- "-c 2048" <<< "$custom" || fail "custom context did not reach the argv"
argv_line="$(printf '%s\n' "$custom" | awk 'found {print; exit} /llama-server argv:/ {found=1}')"
grep -q "Qwen3-4B" <<< "$argv_line" && fail "custom argv fell back to Qwen3-4B"

set +e
bad="$(bash "$SESSION" plan --model-hf 'org/name;rm' --model-alias bad 2>&1)"
bad_status=$?
set -e
[[ "$bad_status" -eq 2 ]] || fail "malicious model reference exited ${bad_status}"
grep -q "Refusing model reference" <<< "$bad" || fail "malicious model reference was not rejected"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

state="${tmp}/state"
mkdir -p "$state"
ssh_log="${tmp}/ssh.log"
: >"$ssh_log"
cat >"${tmp}/ssh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${ssh_log}"
exit 99
EOF
chmod +x "${tmp}/ssh"
cat >"${tmp}/sbatch" <<EOF
#!/usr/bin/env bash
echo sbatch >> "${ssh_log}"
exit 99
EOF
chmod +x "${tmp}/sbatch"

PATH="${tmp}:${PATH}" MAGE_SSH="${tmp}/ssh" MAGE_SBATCH="${tmp}/sbatch" MAGE_STATE_DIR="$state" \
  bash "$EVAL" --dry-run --model-profile qwen36-35b --context 131072 \
    --jump user@scholar.example --partition spark-batch --account scholar \
    --gpus 1 --cpus 20 --mem 100G --time 02:00:00 --condition both --n-tasks 1 \
    >"${tmp}/dry.txt"
grep -q "Dry run" "${tmp}/dry.txt" || fail "eval dry-run did not stay local"
grep -q "#SBATCH --account=scholar" "${tmp}/dry.txt" || fail "dry-run omitted the batch script"
grep -q "Harbor job (baseline):" "${tmp}/dry.txt" || fail "dry-run omitted the baseline job"
grep -q "Harbor job (mage):" "${tmp}/dry.txt" || fail "dry-run omitted the mage job"
grep -q "unverified" "${tmp}/dry.txt" || fail "dry-run claimed a dataset release"
[[ ! -s "$ssh_log" ]] || fail "dry-run invoked ssh or sbatch: $(cat "$ssh_log")"

base_job="$(awk -F': ' '/Harbor job \(baseline\)/ {print $2}' "${tmp}/dry.txt")"
PATH="${tmp}:${PATH}" MAGE_SSH="${tmp}/ssh" MAGE_STATE_DIR="$state" \
  bash "$EVAL" --dry-run --model-profile qwen36-35b --context 8192 --output-limit 1024 --smoke-max-tokens 256 \
    --model-ssh user@scholar-k060 --no-remote-start --condition baseline --n-tasks 1 \
    >"${tmp}/dry-8k.txt"
other_job="$(awk -F': ' '/Harbor job \(baseline\)/ {print $2}' "${tmp}/dry-8k.txt")"
[[ -n "$base_job" && -n "$other_job" && "$base_job" != "$other_job" ]] || fail "context change reused the Harbor job name"
[[ ! -s "$ssh_log" ]] || fail "second dry-run invoked ssh"

set +e
blocked="$(PATH="${tmp}:${PATH}" MAGE_SSH="${tmp}/ssh" MAGE_STATE_DIR="$state" \
  bash "$EVAL" --dry-run --model-profile qwen30b-diagnostic 2>&1)"
blocked_status=$?
set -e
[[ "$blocked_status" -eq 2 ]] || fail "diagnostic profile dry-run exited ${blocked_status}"
grep -q "not benchmark-ready" <<< "$blocked" || fail "diagnostic refusal was unclear"
[[ ! -s "$ssh_log" ]] || fail "diagnostic dry-run invoked ssh"

PATH="${tmp}:${PATH}" MAGE_SSH="${tmp}/ssh" MAGE_STATE_DIR="$state" \
  bash "$EVAL" --dry-run --allow-not-ready --model-profile qwen30b-diagnostic \
    --model-ssh user@scholar-k060 --no-remote-start --condition baseline --n-tasks 1 \
    >"${tmp}/allow.txt"
grep -q "Dry run" "${tmp}/allow.txt" || fail "allow-not-ready dry-run did not finish"
MAGE_STATE_DIR="$state" bash "$EVAL" status >"${tmp}/status.txt"
grep -q "No recorded eval allocation" "${tmp}/status.txt" || fail "status without a run looked allocated"
[[ ! -s "$ssh_log" ]] || fail "status invoked ssh"

cuda="${tmp}/cuda"
mkdir -p "${cuda}/targets/sbsa-linux/lib" "${cuda}/lib64"
for lib in libcudart.so.13 libcublas.so.13 libcublasLt.so.13; do
  : >"${cuda}/targets/sbsa-linux/lib/${lib}"
  : >"${cuda}/lib64/${lib}"
done
MAGE_SKIP_MODULES=1 MAGE_DISABLE_LDCONFIG=1 MAGE_CUDA_ROOT="$cuda" \
  LD_LIBRARY_PATH="" CUDA_ROOT="" \
  mage_configure_cuda
assert_eq "${MAGE_CUDA_INIT}" "fallback" "cuda init"
grep -q "${cuda}/targets/sbsa-linux/lib" <<< "${LD_LIBRARY_PATH}" || fail "fallback did not export the CUDA library path"
[[ "${MAGE_CUDA_INIT_NOTE}" == *"modtree/spark was not loaded"* ]] || fail "fallback claimed the Spark module tree"

empty="${tmp}/empty-cuda"
mkdir -p "$empty"
set +e
missing="$(MAGE_SKIP_MODULES=1 MAGE_DISABLE_LDCONFIG=1 MAGE_CUDA_ROOT="$empty" \
  LD_LIBRARY_PATH="" CUDA_ROOT="" \
  mage_configure_cuda 2>&1)"
missing_status=$?
set -e
[[ "$missing_status" -eq 1 ]] || fail "missing CUDA libs exited ${missing_status}"
grep -q "libcudart.so.13" <<< "$missing" || fail "missing-lib error omitted libcudart.so.13"
grep -q "${empty}" <<< "$missing" || fail "missing-lib error omitted the CUDA root"

unset GGML_CUDA_ENABLE_UNIFIED_MEMORY || true
MAGE_GPU_NAME="NVIDIA GB10" mage_apply_managed_memory auto
assert_eq "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" "1" "GB10 managed memory"
assert_eq "${MAGE_CUDA_MANAGED_REASON}" "gb10-auto" "GB10 reason"
unset GGML_CUDA_ENABLE_UNIFIED_MEMORY || true
MAGE_GPU_NAME="RTX 4090" mage_apply_managed_memory auto
[[ -z "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" ]] || fail "non-GB10 auto enabled managed memory"
assert_eq "${MAGE_CUDA_MANAGED_REASON}" "not-gb10-left-unset" "non-GB10 reason"
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
MAGE_GPU_NAME="RTX 4090" mage_apply_managed_memory off
[[ -z "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" ]] || fail "explicit off left managed memory set"

proc="${tmp}/proc/50"
mkdir -p "$proc"
py - "$proc/stat" <<'PY'
import sys
fields = ["0"] * 20
fields[19] = "99999"
open(sys.argv[1], "w", encoding="utf-8").write("50 (llama-server) " + " ".join(fields) + "\n")
PY
printf 'llama-server\0--port\08080\0--alias\0qwen36-35b\0' >"$proc/cmdline"
pidfile="${tmp}/server.pid"
MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k060" PORT=8080 MODEL_ALIAS=qwen36-35b CONTEXT=4096 \
  mage_write_pid "$pidfile" 50
kill_log="${tmp}/kills"
MAGE_KILL_LOG="$kill_log" MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k099" \
  set +e
stale_out="$(MAGE_KILL_LOG="$kill_log" MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k099" mage_stop_pidfile "$pidfile" 2>&1)"
stale_status=$?
set -e
[[ "$stale_status" -eq 2 ]] || fail "stale host stop exited ${stale_status}: ${stale_out}"
[[ ! -e "$kill_log" ]] || fail "stale pid was signaled: $(cat "$kill_log")"
grep -q "Refusing" <<< "$stale_out" || fail "stale stop was not explained"

py - "$proc/stat" <<'PY'
import sys
fields = ["0"] * 20
fields[19] = "99999"
open(sys.argv[1], "w", encoding="utf-8").write("50 (llama-server) " + " ".join(fields) + "\n")
PY
printf 'llama-server\0--port\08080\0' >"$proc/cmdline"
MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k060" SLURM_JOB_ID=10 PORT=8080 MODEL_ALIAS=qwen36-35b CONTEXT=4096 \
  mage_write_pid "$pidfile" 50
py - "$pidfile" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
data["slurm_job_id"] = "10"
json.dump(data, open(path, "w", encoding="utf-8"))
PY
rm -f "$kill_log"
set +e
job_out="$(MAGE_KILL_LOG="$kill_log" MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k060" SLURM_JOB_ID=11 mage_stop_pidfile "$pidfile" 2>&1)"
job_status=$?
set -e
[[ "$job_status" -eq 2 ]] || fail "foreign SLURM job stop exited ${job_status}"
[[ ! -e "$kill_log" ]] || fail "foreign SLURM job was signaled"
unset SLURM_JOB_ID || true

MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k060" PORT=8080 MODEL_ALIAS=qwen36-35b CONTEXT=4096 \
  mage_write_pid "$pidfile" 50
: >"$kill_log"
MAGE_KILL_LOG="$kill_log" MAGE_PROC_ROOT="${tmp}/proc" MAGE_HOSTNAME="scholar-k060" \
  mage_stop_pidfile "$pidfile" >/dev/null
grep -q '^50$' "$kill_log" || fail "owned pid was not signaled: $(cat "$kill_log")"

assert_eq "$(mage_slurm_state_class PENDING)" "waiting" "pending class"
assert_eq "$(mage_slurm_state_class "CANCELLED by 7")" "terminal" "cancelled class"
assert_eq "$(mage_slurm_state_class FAILED)" "terminal" "failed class"

cancel_log="${tmp}/scancel.log"
squeue_name="${tmp}/squeue-name"
printf '%s\n' "mage-owned" >"$squeue_name"
cat >"${tmp}/squeue" <<EOF
#!/usr/bin/env bash
cat "${squeue_name}"
EOF
cat >"${tmp}/bin-scancel" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "${cancel_log}"
EOF
chmod +x "${tmp}/squeue" "${tmp}/bin-scancel"
: >"$cancel_log"
MAGE_SQUEUE="${tmp}/squeue" MAGE_SCANCEL="${tmp}/bin-scancel" mage_cancel_owned_job 4242 mage-owned
grep -q 4242 "$cancel_log" || fail "owned job was not cancelled"
printf '%s\n' "someone-else" >"$squeue_name"
: >"$cancel_log"
set +e
foreign="$(MAGE_SQUEUE="${tmp}/squeue" MAGE_SCANCEL="${tmp}/bin-scancel" mage_cancel_owned_job 4242 mage-owned 2>&1)"
foreign_status=$?
set -e
[[ "$foreign_status" -eq 1 ]] || fail "foreign cancel exited ${foreign_status}"
[[ ! -s "$cancel_log" ]] || fail "foreign job was cancelled: $(cat "$cancel_log")"
grep -q "Refusing to cancel" <<< "$foreign" || fail "foreign cancel was not explained"

home="${tmp}/home"
mkdir -p "$home"
launcher="${home}/scholar-session"
cat >"$launcher" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" > "$MAGE_CAPTURE/args"
python3 - "$MAGE_CAPTURE/args" "$MAGE_CAPTURE/seen-config" <<'PY'
import pathlib, sys
args = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
marker = "--resolved-config "
path = args.split(marker, 1)[1].split()[0]
pathlib.Path(sys.argv[2]).write_bytes(pathlib.Path(path).read_bytes())
PY
exit 0
EOF
chmod +x "$launcher"
config="${tmp}/resolved.json"
py - "$config" <<'PY'
import json, sys
json.dump({
  "profile": "",
  "model_hf": "",
  "model_file": "/tmp/my model.gguf",
  "model_alias": "local-model",
  "model_revision": "",
  "context": 2048,
  "gpu_layers": 999,
  "flash_attn": "off",
  "parallel": 1,
  "port": 8080,
  "bind": "127.0.0.1",
  "bind_public": False,
  "cuda_managed": "auto",
  "output_limit": 256,
  "smoke_max_tokens": 64,
  "reasoning": "preserve",
  "benchmark_ready": True,
  "temperature": "",
  "llama_extra": [],
  "role": "test",
  "note": "test",
  "warnings": [],
  "contract_version": 1,
  "context_accounting": {},
}, open(sys.argv[1], "w", encoding="utf-8"))
PY
capture="${tmp}/capture"
mkdir -p "$capture"
export MAGE_CAPTURE="$capture"
command_text="$(mage_remote_command "$launcher" "$config" run-quote)"
grep -q 'my model.gguf' <<< "$command_text" && fail "model path was embedded in the remote command"
HOME="$home" bash -c "$command_text"
grep -q "/tmp/my model.gguf" "$capture/seen-config" || fail "remote config lost the model path"
grep -q "serve --resolved-config" "$capture/args" || fail "remote launcher was not called with the config"
unset MAGE_CAPTURE

cat >"${tmp}/ssh-wait" <<EOF
#!/usr/bin/env bash
cmd="\$*"
printf '%s\n' "\$cmd" >> "${tmp}/ssh-wait.log"
if [[ "\$cmd" == *scancel* ]]; then
  printf '%s\n' "\$cmd" >> "${tmp}/cancelled"
  exit 0
fi
if [[ "\$cmd" == *hostname* ]]; then
  exit 0
fi
if [[ "\$cmd" == *%j* ]]; then
  printf '%s\n' "mage-run-wait"
  exit 0
fi
printf '%s\n' "PENDING"
EOF
chmod +x "${tmp}/ssh-wait"
set +e
(
  # shellcheck source=../eval-host
  source "$EVAL"
  KEEP_ALLOCATION=1
  JUMP="user@login"
  OWNED_JOB_ID=77
  OWNED_JOB_NAME="mage-run-wait"
  RUN_ID="run-wait"
  RUN_DIR="${tmp}/wait-run"
  mkdir -p "$RUN_DIR"
  MAGE_SSH="${tmp}/ssh-wait"
  MAGE_POLL_INTERVAL=0
  STARTUP_TIMEOUT=1
  wait_for_host ssh "${tmp}/remote-run" >"${tmp}/wait-out" 2>"${tmp}/wait-err"
)
wait_status=$?
set -e
[[ "$wait_status" -ne 0 ]] || fail "startup timeout returned success"
grep -q "77" "${tmp}/cancelled" || fail "startup timeout did not cancel the owned job"

cat >"${tmp}/ssh-ready" <<EOF
#!/usr/bin/env bash
cmd="\$*"
if [[ "\$cmd" == *hostname* ]]; then
  printf '%s\n' "scholar-k060"
  exit 0
fi
printf '%s\n' "RUNNING"
EOF
chmod +x "${tmp}/ssh-ready"
(
  source "$EVAL"
  KEEP_ALLOCATION=1
  JUMP="user@login"
  OWNED_JOB_ID=88
  OWNED_JOB_NAME="mage-run-ready"
  RUN_ID="run-ready"
  RUN_DIR="${tmp}/ready-run"
  mkdir -p "$RUN_DIR"
  MAGE_SSH="${tmp}/ssh-ready"
  MAGE_POLL_INTERVAL=0
  STARTUP_TIMEOUT=5
  wait_for_host ssh "${tmp}/remote-ready" >"${tmp}/ready-out"
  [[ "$MODEL_SSH" == "user@scholar-k060" ]]
)

echo "scholar pipeline tests passed"
