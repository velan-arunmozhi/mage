#!/bin/bash
# Frozen Qwen3.6 Harbor runner. Do not swap the model, runtime, or agent version.
# Thinking stays off in scripts/reasoning_proxy.py (PROXY_MODE=qwen-off).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Optimal setup, pinned.
MODEL_HF="nvidia/Qwen3.6-35B-A3B-NVFP4"
MODEL_REVISION="1355db6a052410cfd62085d94b58866fd0f2c3c5"
VLLM_VERSION="0.28.0"
OPENCODE_VERSION="1.19.5"
CONTEXT=131072
OUTPUT_LIMIT=8192

NAME="${1:?job name}"
# Optional second arg must be the pinned model. A different id is refused.
REQUESTED="${2:-${MODEL_HF}}"
CONC="${3:-1}"
LIST="${4:-${ROOT}/raw/swebenchpro-12.txt}"
JOBS="${ROOT}/harbor-jobs"
mkdir -p "${JOBS}"
API_MODEL="${REQUESTED#openai/}"
if [[ "${API_MODEL}" != "${MODEL_HF}" ]]; then
  echo "This runner is pinned to ${MODEL_HF} revision ${MODEL_REVISION} on vLLM ${VLLM_VERSION}." >&2
  echo "Refusing ${API_MODEL}." >&2
  exit 2
fi
echo "PIN model=${MODEL_HF} revision=${MODEL_REVISION} vllm=${VLLM_VERSION} opencode=${OPENCODE_VERSION} context=${CONTEXT} output=${OUTPUT_LIMIT} thinking=off"
# A custom provider uses @ai-sdk/openai-compatible, so tool turns go to
# /v1/chat/completions. The built-in openai provider uses /v1/responses,
# which vLLM 0.28 rejects once a tool result is sent back.
HARBOR_MODEL="vllm/${API_MODEL}"
args=()
while IFS= read -r line; do
  [[ -z "${line}" || "${line}" == \#* ]] && continue
  args+=(--include-task-name "${line}")
done < "${LIST}"
exec "${ROOT}/../scripts/harbor-run" run --yes \
  --agent opencode \
  --dataset swebenchpro \
  --n-tasks 12 \
  --n-concurrent "${CONC}" \
  "${args[@]}" \
  --model "${HARBOR_MODEL}" \
  --job-name "${NAME}" \
  --jobs-dir "${JOBS}" \
  --ak "version=${OPENCODE_VERSION}" \
  --ak "opencode_config={\"provider\":{\"vllm\":{\"npm\":\"@ai-sdk/openai-compatible\",\"name\":\"vllm\",\"options\":{\"baseURL\":\"http://host.docker.internal:18082/v1\",\"apiKey\":\"local\"},\"models\":{\"${MODEL_HF}\":{\"name\":\"${MODEL_HF}\",\"limit\":{\"context\":${CONTEXT},\"output\":${OUTPUT_LIMIT}}}}}},\"small_model\":\"${HARBOR_MODEL}\",\"compaction\":{\"auto\":true}}" \
  --ae OPENAI_BASE_URL=http://host.docker.internal:18082/v1 \
  --ae OPENAI_API_KEY=local
