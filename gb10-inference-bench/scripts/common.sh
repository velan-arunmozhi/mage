#!/bin/bash
# Shared paths for the Scholar GB10 benchmark worker.
ROOT=/scratch/scholar/billin19/gb10-inference-bench
export ROOT
export CUDA_HOME=/apps/spack/scholar-dgx/apps/cuda/13.1.1-none-none-hfb3k4d
export PATH="${CUDA_HOME}/bin:${PATH}"
export LD_LIBRARY_PATH="/scratch/scholar/billin19/src/llama.cpp/build-no-vmm/bin:${CUDA_HOME}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export HF_HOME=/scratch/scholar/billin19/hf-cache
export HUGGINGFACE_HUB_CACHE=/scratch/scholar/billin19/hf-cache/hub
export HF_HUB_DISABLE_XET=1
export APPTAINER_CACHEDIR="${ROOT}/apptainer/cache"
export APPTAINER_TMPDIR="${ROOT}/apptainer/tmp"
export LLAMA_BIN=/scratch/scholar/billin19/src/llama.cpp/build-no-vmm/bin
export LLAMA_BENCH="${LLAMA_BIN}/llama-bench"
export LLAMA_BATCH="${LLAMA_BIN}/llama-batched-bench"
export LLAMA_SERVER="${LLAMA_BIN}/llama-server"

export QWEN36_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--unsloth--Qwen3.6-35B-A3B-GGUF/snapshots/a483e9e6cbd595906af30beda3187c2663a1118c/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
export QWEN35_2B_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--unsloth--Qwen3.5-2B-GGUF/snapshots/f6d5376be1edb4d416d56da11e5397a961aca8ae/Qwen3.5-2B-Q4_K_M.gguf"
export QWEN35_9B_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--unsloth--Qwen3.5-9B-GGUF/snapshots/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf"
export QWEN3_4B_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--Qwen--Qwen3-4B-GGUF/snapshots/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf"
export GEMMA4_E4B_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--unsloth--gemma-4-E4B-it-GGUF/snapshots/bfc15c382204943c3a8fff0c750b94ae2364d7a3/gemma-4-E4B-it-Q4_K_M.gguf"
export QWEN35_08B_GGUF="/scratch/scholar/billin19/hf-cache/hub/models--unsloth--Qwen3.5-0.8B-GGUF/snapshots/6ab461498e2023f6e3c1baea90a8f0fe38ab64d0/Qwen3.5-0.8B-Q4_K_M.gguf"

export VLLM_SIF="${ROOT}/apptainer/vllm-openai-0.28.0.sif"
mkdir -p "${ROOT}/logs" "${ROOT}/raw" "${ROOT}/configs" "${ROOT}/state" "${ROOT}/tmp" "${ROOT}/apptainer/cache" "${ROOT}/apptainer/tmp"

llama_env() {
  export LD_LIBRARY_PATH="/scratch/scholar/billin19/src/llama.cpp/build-no-vmm/bin:${CUDA_HOME}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
}
