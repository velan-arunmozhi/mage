# Shared Scholar launcher helpers. Source this file; do not execute it.
# Model settings are resolved by mage_scholar.py. This file owns process
# identity, the CUDA environment, and the SSH/SLURM handoff.

if [[ -z "${MAGE_LIB_DIR:-}" ]]; then
  MAGE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
MAGE_PY="${MAGE_PY:-${MAGE_LIB_DIR}/mage_scholar.py}"
# Full object id. git fetch does not accept this as a 7-character prefix.
MAGE_VERIFIED_LLAMA_COMMIT="${MAGE_VERIFIED_LLAMA_COMMIT:-31288c9c66e59377f7788d920678a565bb89dd37}"
MAGE_VERIFIED_CUDA_ROOT="${MAGE_VERIFIED_CUDA_ROOT:-/apps/spack/scholar-dgx/apps/cuda/13.1.1-none-none-hfb3k4d}"

mage_die() {
  echo "$*" >&2
  exit 1
}

mage_python() {
  if [[ -n "${MAGE_PYTHON:-}" ]]; then
    "$MAGE_PYTHON" "$@"
  elif command -v python3 >/dev/null 2>&1; then
    python3 "$@"
  elif command -v python >/dev/null 2>&1; then
    python "$@"
  else
    mage_die "python3 is required."
  fi
}

mage_json_get() {
  mage_python -c 'import json,sys; value=json.load(open(sys.argv[1],encoding="utf-8")); cur=value
for key in sys.argv[2:]:
    cur=cur[key]
print(cur if not isinstance(cur, bool) else ("true" if cur else "false"))' "$@"
}

mage_reset_cli() {
  CLI_MODEL_PROFILE=""
  CLI_MODEL_HF=""
  CLI_MODEL_FILE=""
  CLI_MODEL_ALIAS=""
  CLI_MODEL_REVISION=""
  CLI_CONTEXT=""
  CLI_GPU_LAYERS=""
  CLI_FLASH_ATTN=""
  CLI_PARALLEL=""
  CLI_PORT=""
  CLI_BIND=""
  CLI_CUDA_MANAGED=""
  CLI_OUTPUT_LIMIT=""
  CLI_SMOKE_MAX_TOKENS=""
  CLI_REASONING=""
  CLI_TEMPERATURE=""
  CLI_CONFIG=""
  CLI_RESOLVED_CONFIG=""
  CLI_LLAMA_ARGS=()
  CLI_SET_PROFILE=0
  CLI_SET_MODEL_HF=0
  CLI_SET_MODEL_FILE=0
  CLI_SET_MODEL_ALIAS=0
  CLI_SET_MODEL_REVISION=0
  CLI_SET_CONTEXT=0
  CLI_SET_GPU_LAYERS=0
  CLI_SET_FLASH_ATTN=0
  CLI_SET_PARALLEL=0
  CLI_SET_PORT=0
  CLI_SET_BIND=0
  CLI_SET_CUDA_MANAGED=0
  CLI_SET_OUTPUT_LIMIT=0
  CLI_SET_SMOKE_MAX_TOKENS=0
  CLI_SET_REASONING=0
  CLI_SET_TEMPERATURE=0
  CLI_SET_LLAMA_ARG=0
  MAGE_SHIFT_N=0
}

mage_require_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    mage_die "${flag} requires a value."
  fi
}

mage_take_model_flag() {
  MAGE_SHIFT_N=0
  case "${1:-}" in
    --model-profile) mage_require_value "$1" "${2:-}"; CLI_MODEL_PROFILE="$2"; CLI_SET_PROFILE=1; MAGE_SHIFT_N=2 ;;
    --model-hf) mage_require_value "$1" "${2:-}"; CLI_MODEL_HF="$2"; CLI_SET_MODEL_HF=1; MAGE_SHIFT_N=2 ;;
    --model-file) mage_require_value "$1" "${2:-}"; CLI_MODEL_FILE="$2"; CLI_SET_MODEL_FILE=1; MAGE_SHIFT_N=2 ;;
    --model-alias) mage_require_value "$1" "${2:-}"; CLI_MODEL_ALIAS="$2"; CLI_SET_MODEL_ALIAS=1; MAGE_SHIFT_N=2 ;;
    --model-revision) mage_require_value "$1" "${2:-}"; CLI_MODEL_REVISION="$2"; CLI_SET_MODEL_REVISION=1; MAGE_SHIFT_N=2 ;;
    --context) mage_require_value "$1" "${2:-}"; CLI_CONTEXT="$2"; CLI_SET_CONTEXT=1; MAGE_SHIFT_N=2 ;;
    --gpu-layers) mage_require_value "$1" "${2:-}"; CLI_GPU_LAYERS="$2"; CLI_SET_GPU_LAYERS=1; MAGE_SHIFT_N=2 ;;
    --flash-attn) mage_require_value "$1" "${2:-}"; CLI_FLASH_ATTN="$2"; CLI_SET_FLASH_ATTN=1; MAGE_SHIFT_N=2 ;;
    --parallel) mage_require_value "$1" "${2:-}"; CLI_PARALLEL="$2"; CLI_SET_PARALLEL=1; MAGE_SHIFT_N=2 ;;
    --port) mage_require_value "$1" "${2:-}"; CLI_PORT="$2"; CLI_SET_PORT=1; MAGE_SHIFT_N=2 ;;
    --bind) mage_require_value "$1" "${2:-}"; CLI_BIND="$2"; CLI_SET_BIND=1; MAGE_SHIFT_N=2 ;;
    --cuda-managed) mage_require_value "$1" "${2:-}"; CLI_CUDA_MANAGED="$2"; CLI_SET_CUDA_MANAGED=1; MAGE_SHIFT_N=2 ;;
    --output-limit) mage_require_value "$1" "${2:-}"; CLI_OUTPUT_LIMIT="$2"; CLI_SET_OUTPUT_LIMIT=1; MAGE_SHIFT_N=2 ;;
    --smoke-max-tokens) mage_require_value "$1" "${2:-}"; CLI_SMOKE_MAX_TOKENS="$2"; CLI_SET_SMOKE_MAX_TOKENS=1; MAGE_SHIFT_N=2 ;;
    --reasoning) mage_require_value "$1" "${2:-}"; CLI_REASONING="$2"; CLI_SET_REASONING=1; MAGE_SHIFT_N=2 ;;
    --temperature) mage_require_value "$1" "${2:-}"; CLI_TEMPERATURE="$2"; CLI_SET_TEMPERATURE=1; MAGE_SHIFT_N=2 ;;
    --config) mage_require_value "$1" "${2:-}"; CLI_CONFIG="$2"; MAGE_SHIFT_N=2 ;;
    --resolved-config) mage_require_value "$1" "${2:-}"; CLI_RESOLVED_CONFIG="$2"; MAGE_SHIFT_N=2 ;;
    --llama-arg)
      mage_require_value "$1" "${2:-}"
      CLI_LLAMA_ARGS+=("$2")
      CLI_SET_LLAMA_ARG=1
      MAGE_SHIFT_N=2
      ;;
    *) return 1 ;;
  esac
}

mage_resolve_file() {
  local dest="$1"
  local -a args=(resolve)
  [[ "$CLI_SET_PROFILE" -eq 1 ]] && args+=(--model-profile "$CLI_MODEL_PROFILE")
  [[ "$CLI_SET_MODEL_HF" -eq 1 ]] && args+=(--model-hf "$CLI_MODEL_HF")
  [[ "$CLI_SET_MODEL_FILE" -eq 1 ]] && args+=(--model-file "$CLI_MODEL_FILE")
  [[ "$CLI_SET_MODEL_ALIAS" -eq 1 ]] && args+=(--model-alias "$CLI_MODEL_ALIAS")
  [[ "$CLI_SET_MODEL_REVISION" -eq 1 ]] && args+=(--model-revision "$CLI_MODEL_REVISION")
  [[ "$CLI_SET_CONTEXT" -eq 1 ]] && args+=(--context "$CLI_CONTEXT")
  [[ "$CLI_SET_GPU_LAYERS" -eq 1 ]] && args+=(--gpu-layers "$CLI_GPU_LAYERS")
  [[ "$CLI_SET_FLASH_ATTN" -eq 1 ]] && args+=(--flash-attn "$CLI_FLASH_ATTN")
  [[ "$CLI_SET_PARALLEL" -eq 1 ]] && args+=(--parallel "$CLI_PARALLEL")
  [[ "$CLI_SET_PORT" -eq 1 ]] && args+=(--port "$CLI_PORT")
  [[ "$CLI_SET_BIND" -eq 1 ]] && args+=(--bind "$CLI_BIND")
  [[ "$CLI_SET_CUDA_MANAGED" -eq 1 ]] && args+=(--cuda-managed "$CLI_CUDA_MANAGED")
  [[ "$CLI_SET_OUTPUT_LIMIT" -eq 1 ]] && args+=(--output-limit "$CLI_OUTPUT_LIMIT")
  [[ "$CLI_SET_SMOKE_MAX_TOKENS" -eq 1 ]] && args+=(--smoke-max-tokens "$CLI_SMOKE_MAX_TOKENS")
  [[ "$CLI_SET_REASONING" -eq 1 ]] && args+=(--reasoning "$CLI_REASONING")
  [[ "$CLI_SET_TEMPERATURE" -eq 1 ]] && args+=(--temperature "$CLI_TEMPERATURE")
  [[ -n "$CLI_CONFIG" ]] && args+=(--config "$CLI_CONFIG")
  [[ -n "$CLI_RESOLVED_CONFIG" ]] && args+=(--resolved-config "$CLI_RESOLVED_CONFIG")
  if [[ "$CLI_SET_LLAMA_ARG" -eq 1 ]]; then
    local extra
    for extra in "${CLI_LLAMA_ARGS[@]}"; do
      args+=(--llama-arg "$extra")
    done
  fi
  local err
  err="$(mktemp)"
  if ! mage_python "$MAGE_PY" "${args[@]}" >"$dest" 2>"$err"; then
    cat "$err" >&2
    rm -f "$err"
    exit 2
  fi
  rm -f "$err"
}

mage_print_warnings() {
  local file="$1"
  mage_python -c 'import json,sys; data=json.load(open(sys.argv[1],encoding="utf-8"));
[print(item, file=sys.stderr) for item in data.get("warnings") or []]' "$file"
}

mage_load_resolved() {
  local file="$1"
  MAGE_RESOLVED_FILE="$file"
  MODEL_HF="$(mage_json_get "$file" model_hf)"
  MODEL_FILE="$(mage_json_get "$file" model_file)"
  MODEL_ALIAS="$(mage_json_get "$file" model_alias)"
  MODEL_REVISION="$(mage_json_get "$file" model_revision)"
  CONTEXT="$(mage_json_get "$file" context)"
  GPU_LAYERS="$(mage_json_get "$file" gpu_layers)"
  FLASH_ATTN="$(mage_json_get "$file" flash_attn)"
  PARALLEL="$(mage_json_get "$file" parallel)"
  PORT="$(mage_json_get "$file" port)"
  BIND="$(mage_json_get "$file" bind)"
  BIND_PUBLIC="$(mage_json_get "$file" bind_public)"
  CUDA_MANAGED="$(mage_json_get "$file" cuda_managed)"
  OUTPUT_LIMIT="$(mage_json_get "$file" output_limit)"
  SMOKE_MAX_TOKENS="$(mage_json_get "$file" smoke_max_tokens)"
  REASONING="$(mage_json_get "$file" reasoning)"
  BENCHMARK_READY="$(mage_json_get "$file" benchmark_ready)"
  PROFILE_NAME="$(mage_json_get "$file" profile)"
}

mage_ensure_home() {
  if [[ -n "${HOME:-}" && -d "${HOME}" ]]; then
    return 0
  fi
  local user home
  user="$(id -un 2>/dev/null || true)"
  home=""
  if [[ -n "$user" ]] && command -v getent >/dev/null 2>&1; then
    home="$(getent passwd "$user" | awk -F: '{print $6}')"
  fi
  if [[ -n "$home" && -d "$home" ]]; then
    export HOME="$home"
    echo "HOME was unset. Using ${HOME} from the passwd database."
    return 0
  fi
  mage_die "HOME is unset and could not be resolved from the passwd database."
}

mage_ensure_scratch() {
  if [[ -n "${MAGE_SCRATCH:-}" ]]; then
    mkdir -p "${MAGE_SCRATCH}" || mage_die "Could not create scratch root ${MAGE_SCRATCH}."
    return 0
  fi
  if [[ -n "${RCAC_SCRATCH:-}" && -d "${RCAC_SCRATCH}" ]]; then
    return 0
  fi
  local user candidate
  user="$(id -un 2>/dev/null || true)"
  if [[ -n "$user" ]]; then
    for candidate in "/scratch/scholar/${user}" "/scratch/${user}"; do
      if [[ -d "$candidate" ]]; then
        export RCAC_SCRATCH="$candidate"
        echo "RCAC_SCRATCH was unset. Using existing directory ${RCAC_SCRATCH}."
        return 0
      fi
    done
  fi
  mage_die "RCAC_SCRATCH is unset and no existing Scholar scratch directory was found for ${user:-this user}. Pass --scratch PATH. This script does not create a guessed scratch root."
}

mage_prepare_roots() {
  mage_ensure_home
  mage_ensure_scratch
  ROOT="${MAGE_SCRATCH:-${RCAC_SCRATCH}/mage-bench}"
  mkdir -p "${ROOT}"
  if [[ -z "${HF_HOME:-}" ]]; then
    if [[ -n "${RCAC_SCRATCH:-}" ]]; then
      export HF_HOME="${RCAC_SCRATCH}/hf-cache"
    else
      export HF_HOME="${ROOT}/hf-cache"
    fi
  fi
  mkdir -p "${HF_HOME}" "${ROOT}/tmp"
  export TMPDIR="${ROOT}/tmp"
  LLAMA_SRC="${MAGE_LLAMA_SRC:-${ROOT}/llama.cpp}"
  RUN_ID="${MAGE_RUN_ID:-$(mage_new_run_id)}"
  RUN_DIR="${MAGE_RUN_DIR:-${ROOT}/runs/${RUN_ID}}"
  mkdir -p "${RUN_DIR}"
  printf '%s\n' "${RUN_ID}" >"${ROOT}/current-run"
  PIDFILE="${RUN_DIR}/llama-server.pid"
  LOGFILE="${RUN_DIR}/llama-server.log"
}

mage_new_run_id() {
  local stamp hex
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  hex="$(mage_python -c 'import secrets; print(secrets.token_hex(4))')"
  printf 'run-%s-%s' "$stamp" "$hex"
}

mage_hostname() {
  if [[ -n "${MAGE_HOSTNAME:-}" ]]; then
    printf '%s' "${MAGE_HOSTNAME}"
  else
    hostname
  fi
}

mage_missing_cuda_libs() {
  local name missing=""
  for name in libcudart.so.13 libcublas.so.13 libcublasLt.so.13; do
    if ! mage_lib_find "$name"; then
      missing="${missing}${name}"$'\n'
    fi
  done
  printf '%s' "$missing"
}

mage_lib_find() {
  local name="$1"
  local dir
  local -a paths=()
  if [[ -n "${CUDA_ROOT:-}" ]]; then
    paths+=("${CUDA_ROOT}/targets/sbsa-linux/lib" "${CUDA_ROOT}/lib64" "${CUDA_ROOT}/lib")
  fi
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    local part
    IFS=':' read -ra part <<< "${LD_LIBRARY_PATH}"
    paths+=("${part[@]}")
  fi
  for dir in "${paths[@]}"; do
    [[ -n "$dir" ]] || continue
    if [[ -e "${dir}/${name}" || -e "${dir}/${name}.1" ]]; then
      return 0
    fi
  done
  if [[ "${MAGE_DISABLE_LDCONFIG:-}" != 1 ]] && command -v ldconfig >/dev/null 2>&1; then
    if ldconfig -p 2>/dev/null | grep -F -q "$name"; then
      return 0
    fi
  fi
  return 1
}

mage_try_modules() {
  if [[ "${MAGE_SKIP_MODULES:-}" == 1 ]]; then
    return 1
  fi
  if ! type module >/dev/null 2>&1; then
    local candidate
    local -a candidates=()
    if [[ -n "${MAGE_MODULE_CANDIDATES:-}" ]]; then
      read -ra candidates <<< "${MAGE_MODULE_CANDIDATES}"
    else
      candidates=(/etc/profile.d/modules.sh /usr/share/lmod/lmod/init/bash /usr/share/Modules/init/bash)
    fi
    for candidate in "${candidates[@]}"; do
      if [[ -f "$candidate" ]]; then
        # Lmod reads FPATH. Under set -u an unset FPATH aborts the source.
        FPATH="${FPATH:-}"
        # shellcheck disable=SC1090
        source "$candidate" || true
        break
      fi
    done
  fi
  if ! type module >/dev/null 2>&1; then
    return 1
  fi
  module load modtree/spark || return 1
  module load conda cuda cmake || return 1
  return 0
}

mage_configure_cuda() {
  local missing modules_status root root_source
  missing="$(mage_missing_cuda_libs)"
  if [[ -z "$missing" ]]; then
    MAGE_CUDA_INIT="preexisting"
    return 0
  fi
  modules_status="unavailable"
  if mage_try_modules; then
    modules_status="loaded"
    missing="$(mage_missing_cuda_libs)"
    if [[ -z "$missing" ]]; then
      MAGE_CUDA_INIT="modules"
      return 0
    fi
    modules_status="loaded-but-cuda-13-libs-missing"
  fi
  if [[ -n "${MAGE_CUDA_ROOT:-}" ]]; then
    root="${MAGE_CUDA_ROOT}"
    root_source="MAGE_CUDA_ROOT"
    if [[ ! -d "$root" ]]; then
      mage_die_cuda "$modules_status" "$root" "$root_source" "$missing"
    fi
  else
    root="${MAGE_VERIFIED_CUDA_ROOT}"
    root_source="verified Scholar DGX CUDA 13.1.1 path"
    if [[ ! -d "$root" ]]; then
      mage_die_cuda "$modules_status" "$root" "$root_source" "$missing"
    fi
  fi
  export CUDA_ROOT="$root"
  export PATH="${CUDA_ROOT}/bin:${PATH}"
  export LD_LIBRARY_PATH="${CUDA_ROOT}/targets/sbsa-linux/lib:${CUDA_ROOT}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  missing="$(mage_missing_cuda_libs)"
  if [[ -n "$missing" ]]; then
    mage_die_cuda "$modules_status" "$root" "$root_source" "$missing"
  fi
  MAGE_CUDA_INIT="fallback"
  MAGE_CUDA_INIT_NOTE="CUDA libraries came from ${root}. modtree/spark was not loaded by this fallback."
  echo "${MAGE_CUDA_INIT_NOTE}"
}

mage_die_cuda() {
  local modules_status="$1"
  local root="$2"
  local root_source="$3"
  local missing="$4"
  cat >&2 <<EOF
CUDA runtime libraries are not usable.
Missing:
${missing:-unknown}
module status: ${modules_status}
CUDA root (${root_source}): ${root}
binary: ${MAGE_LLAMA_BIN_RESOLVED:-unset}
log: ${LOGFILE:-unset}
LD_LIBRARY_PATH: ${LD_LIBRARY_PATH:-unset}

The verified Scholar fallback is ${MAGE_VERIFIED_CUDA_ROOT}. That path is specific to the observed Scholar DGX installation, not a universal CUDA location. Loading this path does not mean modtree/spark was loaded. A successful managed-memory run used this direct CUDA 13.1 configuration because some batch shells have no module command and no /etc/profile.d/modules.sh.
EOF
  exit 1
}

mage_is_gb10() {
  local names
  names="$(mage_gpu_names || true)"
  grep -qi 'GB10' <<< "$names"
}

mage_gpu_names() {
  if [[ -n "${MAGE_GPU_NAME:-}" ]]; then
    printf '%s\n' "${MAGE_GPU_NAME}"
    return 0
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || true
  fi
}

mage_apply_managed_memory() {
  local mode="$1"
  MAGE_CUDA_MANAGED_REASON=""
  case "$mode" in
    on)
      export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
      MAGE_CUDA_MANAGED_REASON="explicit-on"
      ;;
    off)
      unset GGML_CUDA_ENABLE_UNIFIED_MEMORY || true
      MAGE_CUDA_MANAGED_REASON="explicit-off"
      ;;
    auto)
      if [[ -n "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" ]]; then
        MAGE_CUDA_MANAGED_REASON="preexisting-env"
      elif mage_is_gb10; then
        export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
        MAGE_CUDA_MANAGED_REASON="gb10-auto"
      else
        MAGE_CUDA_MANAGED_REASON="not-gb10-left-unset"
      fi
      ;;
    *)
      mage_die "Internal error: cuda managed mode ${mode}."
      ;;
  esac
  MAGE_CUDA_MANAGED_EFFECTIVE="${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-unset}"
  echo "GGML_CUDA_ENABLE_UNIFIED_MEMORY=${MAGE_CUDA_MANAGED_EFFECTIVE} (${MAGE_CUDA_MANAGED_REASON})"
}

mage_require_gpu() {
  if [[ "${MAGE_SKIP_GPU:-}" == 1 ]]; then
    return 0
  fi
  command -v nvidia-smi >/dev/null 2>&1 || mage_die "nvidia-smi is not on PATH. Start serve inside a Scholar GPU allocation."
  nvidia-smi -L >/dev/null 2>&1 || mage_die "No GPU is visible. Request one with salloc or sinteractive before serve. Example: salloc -A scholar -p spark-batch --gres=gpu:1 --cpus-per-task=20 --mem=100G --time=02:00:00"
}

mage_proc_starttime() {
  local pid="$1"
  local statfile="${MAGE_PROC_ROOT:-/proc}/${pid}/stat"
  [[ -f "$statfile" ]] || return 1
  mage_python -c 'import pathlib,sys; text=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"); right=text.rindex(")"); fields=text[right+2:].split(); print(fields[19])' "$statfile"
}

mage_proc_cmdline() {
  local pid="$1"
  local file="${MAGE_PROC_ROOT:-/proc}/${pid}/cmdline"
  [[ -f "$file" ]] || return 1
  tr '\0' ' ' <"$file"
}

mage_write_pid() {
  local dest="$1"
  local pid="$2"
  local starttime="" binary tries=0
  while [[ -z "$starttime" && "$tries" -lt 20 ]]; do
    starttime="$(mage_proc_starttime "$pid" || true)"
    if [[ -z "$starttime" ]]; then
      sleep 0.1
    fi
    tries=$((tries + 1))
  done
  binary="${MAGE_LLAMA_BIN_RESOLVED:-}"
  MAGE_PID_DEST="$dest" \
  MAGE_PID_VALUE="$pid" \
  MAGE_PID_STARTTIME="$starttime" \
  MAGE_PID_HOSTNAME="$(mage_hostname)" \
  MAGE_PID_JOB="${SLURM_JOB_ID:-}" \
  MAGE_PID_PORT="$PORT" \
  MAGE_PID_ALIAS="$MODEL_ALIAS" \
  MAGE_PID_CONTEXT="$CONTEXT" \
  MAGE_PID_BINARY="$binary" \
  mage_python - <<'PY'
import json, os
from pathlib import Path
payload = {
    "pid": int(os.environ["MAGE_PID_VALUE"]),
    "starttime": os.environ.get("MAGE_PID_STARTTIME", ""),
    "hostname": os.environ.get("MAGE_PID_HOSTNAME", ""),
    "slurm_job_id": os.environ.get("MAGE_PID_JOB", ""),
    "port": int(os.environ["MAGE_PID_PORT"]),
    "alias": os.environ.get("MAGE_PID_ALIAS", ""),
    "context": int(os.environ["MAGE_PID_CONTEXT"]),
    "binary": os.environ.get("MAGE_PID_BINARY", ""),
}
Path(os.environ["MAGE_PID_DEST"]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

mage_pid_state() {
  local pidfile="$1"
  MAGE_PID_DETAIL=""
  MAGE_PID_VALUE=""
  MAGE_PID_STATE="dead"
  if [[ ! -f "$pidfile" ]]; then
    echo dead
    return 0
  fi
  local pid start host job port cmdline now_start here
  pid="$(mage_json_get "$pidfile" pid)"
  start="$(mage_json_get "$pidfile" starttime)"
  host="$(mage_json_get "$pidfile" hostname)"
  job="$(mage_json_get "$pidfile" slurm_job_id)"
  port="$(mage_json_get "$pidfile" port)"
  MAGE_PID_VALUE="$pid"
  if [[ ! -e "${MAGE_PROC_ROOT:-/proc}/${pid}/cmdline" ]]; then
    echo dead
    return 0
  fi
  now_start="$(mage_proc_starttime "$pid" || true)"
  cmdline="$(mage_proc_cmdline "$pid" || true)"
  if [[ -z "$start" || -z "$now_start" || "$now_start" != "$start" || "$cmdline" != *"llama-server"* ]]; then
    MAGE_PID_DETAIL="pid ${pid} is not the llama-server process recorded in ${pidfile}."
    MAGE_PID_STATE="stale"
    echo stale
    return 0
  fi
  if [[ "$cmdline" != *"--port ${port}"* && "$cmdline" != *"--port=${port}"* ]]; then
    MAGE_PID_DETAIL="pid ${pid} is llama-server but its command does not include port ${port}."
    MAGE_PID_STATE="stale"
    echo stale
    return 0
  fi
  here="$(mage_hostname)"
  if [[ -n "$host" && "$host" != "$here" ]]; then
    MAGE_PID_DETAIL="pid file belongs to ${host}; this host is ${here}."
    MAGE_PID_STATE="stale"
    echo stale
    return 0
  fi
  if [[ -n "$job" && -n "${SLURM_JOB_ID:-}" && "$job" != "${SLURM_JOB_ID}" ]]; then
    MAGE_PID_DETAIL="pid file belongs to SLURM job ${job}; this shell is job ${SLURM_JOB_ID}."
    MAGE_PID_STATE="stale"
    echo stale
    return 0
  fi
  MAGE_PID_STATE="alive"
  echo alive
}

mage_signal() {
  if [[ -n "${MAGE_KILL_LOG:-}" ]]; then
    printf '%s\n' "$*" >>"${MAGE_KILL_LOG}"
    return 0
  fi
  kill "$@"
}

mage_stop_pidfile() {
  local pidfile="$1"
  mage_pid_state "$pidfile" >/dev/null
  case "$MAGE_PID_STATE" in
    dead)
      rm -f "$pidfile"
      echo "No owned llama-server is running."
      ;;
    stale)
      echo "Refusing to signal a process that is not the owned llama-server. ${MAGE_PID_DETAIL}" >&2
      mv -f "$pidfile" "${pidfile}.stale"
      return 2
      ;;
    alive)
      mage_signal "${MAGE_PID_VALUE}"
      rm -f "$pidfile"
      echo "Stopped owned llama-server pid ${MAGE_PID_VALUE}."
      ;;
  esac
}

mage_server_argv_file() {
  local resolved="$1"
  local binary="$2"
  local dest="$3"
  mage_python "$MAGE_PY" argv --resolved "$resolved" --binary "$binary" >"$dest"
}

mage_check_llama_help() {
  local bin="$1"
  if [[ "${MAGE_SKIP_LLAMA_HELP:-}" == 1 ]]; then
    return 0
  fi
  local helpfile token
  helpfile="$(mktemp)"
  if ! "$bin" --help >"$helpfile" 2>&1; then
    true
  fi
  for token in alias jinja port flash; do
    if ! grep -qi "$token" "$helpfile"; then
      cat >&2 <<EOF
llama-server at ${bin} did not advertise '${token}' in --help.
The verified build is llama.cpp commit ${MAGE_VERIFIED_LLAMA_COMMIT}. This launcher does not invent replacement flags.
Help output saved beside the server log when a run directory exists.
EOF
      if [[ -n "${RUN_DIR:-}" ]]; then
        cp "$helpfile" "${RUN_DIR}/llama-server-help.txt" || true
      fi
      rm -f "$helpfile"
      exit 1
    fi
  done
  rm -f "$helpfile"
}

mage_check_binary_libs() {
  local bin="$1"
  if ! command -v ldd >/dev/null 2>&1; then
    return 0
  fi
  local missing
  missing="$(ldd "$bin" 2>/dev/null | awk '/not found/ {print}' || true)"
  if [[ -n "$missing" ]]; then
    mage_die "llama-server at ${bin} is missing shared libraries:
${missing}
log: ${LOGFILE:-unset}
CUDA root: ${CUDA_ROOT:-unset}"
  fi
}

mage_write_environment() {
  local dest="$1"
  local bin="$2"
  {
    echo "hostname=$(mage_hostname)"
    echo "uname=$(uname -a 2>/dev/null || true)"
    echo "slurm_job_id=${SLURM_JOB_ID:-}"
    echo "slurm_nodelist=${SLURM_JOB_NODELIST:-}"
    echo "cuda_init=${MAGE_CUDA_INIT:-unknown}"
    echo "cuda_init_note=${MAGE_CUDA_INIT_NOTE:-}"
    echo "cuda_root=${CUDA_ROOT:-}"
    echo "ggml_cuda_enable_unified_memory=${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-unset}"
    echo "cuda_managed_reason=${MAGE_CUDA_MANAGED_REASON:-}"
    echo "hf_home=${HF_HOME:-}"
    echo "llama_bin=${bin}"
    echo "ld_library_path=${LD_LIBRARY_PATH:-}"
    if command -v nvcc >/dev/null 2>&1; then
      echo "nvcc:"
      nvcc --version 2>&1 | head -n 12 || true
    else
      echo "nvcc=missing"
    fi
    if [[ -n "$bin" && -x "$bin" ]]; then
      echo "llama-server --version:"
      "$bin" --version 2>&1 | head -n 20 || true
    fi
    if command -v nvidia-smi >/dev/null 2>&1; then
      echo "nvidia-smi:"
      nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null || true
      echo "note=nvidia-smi memory.total does not measure CUDA managed unified allocations on GB10."
    else
      echo "nvidia-smi=missing"
    fi
    local cgroup
    for cgroup in /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory/memory.usage_in_bytes; do
      if [[ -r "$cgroup" ]]; then
        echo "cgroup_memory_path=${cgroup}"
        echo "cgroup_memory_bytes=$(cat "$cgroup")"
      fi
    done
  } >"$dest"
}

mage_curl_json() {
  local url="$1"
  local dest="$2"
  local tmp
  tmp="$(mktemp)"
  if curl -sf --max-time "${MAGE_CURL_TIMEOUT:-20}" "$url" >"$tmp"; then
    if mage_python -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$tmp" >/dev/null 2>&1; then
      mv "$tmp" "$dest"
      return 0
    fi
  fi
  rm -f "$tmp"
  return 1
}

mage_verify_endpoint() {
  local base="$1"
  local dest="$2"
  local models="$dest/models.json"
  local slots="$dest/slots.json"
  local props="$dest/props.json"
  local verdict="$dest/load-verdict.json"
  mkdir -p "$dest"
  if ! mage_curl_json "${base}/v1/models" "$models"; then
    return 1
  fi
  if ! mage_curl_json "${base}/slots" "$slots"; then
    printf '%s\n' '{}' >"$slots"
  fi
  if ! mage_curl_json "${base}/props" "$props"; then
    printf '%s\n' '{}' >"$props"
  fi
  if ! mage_python "$MAGE_PY" judge-models --alias "$MODEL_ALIAS" --context "$CONTEXT" --models "$models" --slots "$slots" --props "$props" >"$verdict"; then
    return 1
  fi
  [[ -s "$verdict" ]] || return 1
  [[ "$(mage_json_get "$verdict" ok)" == "true" ]]
}

mage_smoke_chat() {
  local base="$1"
  local dest="$2"
  mkdir -p "$dest"
  mage_python "$MAGE_PY" chat-request --resolved "$MAGE_RESOLVED_FILE" >"$dest/request.json"
  if ! curl -sf --max-time "${MAGE_SMOKE_TIMEOUT:-600}" \
    -H 'Content-Type: application/json' \
    --data-binary @"$dest/request.json" \
    "${base}/v1/chat/completions" >"$dest/response.json"; then
    echo "Chat smoke request failed. See ${dest} and ${LOGFILE:-the server log}." >&2
    return 1
  fi
  mage_python "$MAGE_PY" judge-chat "$dest/response.json" >"$dest/verdict.json"
  [[ "$(mage_json_get "$dest/verdict.json" ok)" == "true" ]]
}

mage_smoke_tool() {
  local base="$1"
  local dest="$2"
  mkdir -p "$dest"
  mage_python "$MAGE_PY" tool-request --resolved "$MAGE_RESOLVED_FILE" >"$dest/request.json"
  curl -sf --max-time "${MAGE_SMOKE_TIMEOUT:-600}" \
    -H 'Content-Type: application/json' \
    --data-binary @"$dest/request.json" \
    "${base}/v1/chat/completions" >"$dest/response.json" || return 1
  mage_python "$MAGE_PY" judge-tool "$dest/response.json" >"$dest/verdict.json"
  [[ "$(mage_json_get "$dest/verdict.json" ok)" == "true" ]] || return 1
  mage_python "$MAGE_PY" tool-followup --resolved "$MAGE_RESOLVED_FILE" --verdict "$dest/verdict.json" >"$dest/followup-request.json"
  curl -sf --max-time "${MAGE_SMOKE_TIMEOUT:-600}" \
    -H 'Content-Type: application/json' \
    --data-binary @"$dest/followup-request.json" \
    "${base}/v1/chat/completions" >"$dest/followup-response.json" || return 1
  mage_python "$MAGE_PY" judge-chat "$dest/followup-response.json" >"$dest/followup-verdict.json"
  [[ "$(mage_json_get "$dest/followup-verdict.json" ok)" == "true" ]]
}

mage_remote_body() {
  cat <<'EOF'
set -euo pipefail
repo=$1
payload=$2
run_id=$3
scratch=${4:-}
commit=${5:-}
case $run_id in
  ""|*[!A-Za-z0-9._-]*) echo "invalid run id" >&2; exit 2 ;;
esac
if [[ -z ${HOME:-} || ! -d ${HOME:-} ]]; then
  _user=$(id -un)
  HOME=$(getent passwd "$_user" | awk -F: '{print $6}')
  export HOME
fi
if [[ -z ${HOME:-} || ! -d ${HOME:-} ]]; then
  echo "HOME is unset on the remote shell and passwd lookup failed." >&2
  exit 2
fi
case $repo in
  "~/"*) repo="${HOME}/${repo#~/}" ;;
  "~") repo="${HOME}" ;;
esac
case $repo in
  *$'\n'*|*$'\r'*) echo "remote path contains a newline" >&2; exit 2 ;;
esac
run_dir="${HOME}/mage-eval-jobs/${run_id}"
mkdir -p "$run_dir"
printf '%s' "$payload" | base64 -d > "$run_dir/model-config.json"
export MAGE_RUN_ID="$run_id"
export MAGE_RUN_DIR="$run_dir"
if [[ -n "$scratch" ]]; then
  case $scratch in
    *[!A-Za-z0-9_./@~+-]*) echo "invalid scratch path" >&2; exit 2 ;;
  esac
  export MAGE_SCRATCH="$scratch"
fi
if [[ -n "$commit" ]]; then
  case $commit in
    *[!0-9a-fA-F]*) echo "invalid llama commit" >&2; exit 2 ;;
  esac
  if [[ ${#commit} -lt 7 || ${#commit} -gt 40 ]]; then
    echo "invalid llama commit" >&2
    exit 2
  fi
  exec bash "$repo" serve --resolved-config "$run_dir/model-config.json" --llama-commit "$commit"
fi
exec bash "$repo" serve --resolved-config "$run_dir/model-config.json"
EOF
}

mage_remote_command() {
  local launcher="$1"
  local config_file="$2"
  local run_id="$3"
  local scratch="${4:-}"
  local commit="${5:-}"
  local payload body
  payload="$(mage_python -c 'import base64,pathlib,sys; print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$config_file")"
  body="$(mage_remote_body)"
  printf 'bash --noprofile --norc -c %q _ %q %q %q %q %q' "$body" "$launcher" "$payload" "$run_id" "$scratch" "$commit"
}

mage_slurm_state_class() {
  local state="${1%% *}"
  state="${state%%+*}"
  case "$state" in
    "" ) echo unknown ;;
    PENDING|CONFIGURING|RUNNING|COMPLETING|SUSPENDED) echo waiting ;;
    COMPLETED|FAILED|CANCELLED|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|BOOT_FAIL|DEADLINE) echo terminal ;;
    *) echo unknown ;;
  esac
}

mage_cancel_owned_job() {
  local job_id="$1"
  local expected_name="$2"
  local ssh_target="${3:-}"
  local -a prefix=()
  if [[ -n "$ssh_target" ]]; then
    prefix=("${MAGE_SSH:-ssh}" "$ssh_target")
  fi
  local observed
  observed="$("${prefix[@]}" "${MAGE_SQUEUE:-squeue}" -j "$job_id" -h -o "%j" 2>/dev/null | awk 'NR==1 {print $1}' || true)"
  if [[ -z "$observed" ]]; then
    echo "SLURM job ${job_id} is not in the queue. It was not cancelled."
    return 0
  fi
  if [[ "$observed" != "$expected_name" ]]; then
    mage_die "Refusing to cancel job ${job_id}: queue name '${observed}' does not match owned name '${expected_name}'."
  fi
  "${prefix[@]}" "${MAGE_SCANCEL:-scancel}" "$job_id"
  echo "Cancelled owned SLURM job ${job_id} (${expected_name})."
}

mage_b64_config() {
  mage_python -c 'import base64,pathlib,sys; print(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$1"
}
