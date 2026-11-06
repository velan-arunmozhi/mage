# Models checked

Checked on 2026-10-25. Revisions below are the ones already in the Scholar Hugging Face cache or the official repository identity. Engine support is not claimed until a server in this session actually loads the checkpoint.

| Model | Hugging Face ID | Format on disk | Notes |
|---|---|---|---|
| Qwen3.6-35B-A3B | `unsloth/Qwen3.6-35B-A3B-GGUF` revision `a483e9e6cbd595906af30beda3187c2663a1118c` | GGUF `UD-Q4_K_M` (21 GB) plus `mmproj-BF16.gguf` | Instruction/vision GGUF. Native context is the GGUF metadata; historical server runs used 8192 and 131072. Benchmarks pass the language GGUF path directly so the vision projector is not loaded. https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF |
| Qwen3.6-35B-A3B NVFP4 | `nvidia/Qwen3.6-35B-A3B-NVFP4` | Not cached yet | 35B total, 3B active, 262144 native context, Apache-2.0. Official DGX Spark recipe uses vLLM, FP8 KV, FlashInfer, Marlin MoE, MTP. https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4 |
| Qwen3.5-2B | `unsloth/Qwen3.5-2B-GGUF` revision `f6d5376be1edb4d416d56da11e5397a961aca8ae` | GGUF `Q4_K_M` (1.2 GB) | Speed reference. https://huggingface.co/unsloth/Qwen3.5-2B-GGUF |
| Qwen3.5-9B | `unsloth/Qwen3.5-9B-GGUF` revision `3885219b6810b007914f3a7950a8d1b469d598a5` | GGUF `Q4_K_M` (5.3 GB) | Cached. Not in the first automatic sweep. |
| Qwen3-4B | `Qwen/Qwen3-4B-GGUF` revision `bc640142c66e1fdd12af0bd68f40445458f3869b` | GGUF `Q4_K_M` (2.4 GB) | Cached dense reference. This is Qwen3-4B, not a Qwen3.5-4B checkpoint. |
| Qwen3.5-0.8B | `unsloth/Qwen3.5-0.8B-GGUF` | GGUF `Q4_K_M` (503 MB) | Cached. Speed-only. |
| Gemma 4 E4B | `unsloth/gemma-4-E4B-it-GGUF` | GGUF `Q4_K_M` (4.6 GB) | Cached. |
| Ornith 1.5 | `ornith-ai/Ornith-1.5-35B-A3B-NVFP4` | Not cached | Planned after Qwen3.6 NVFP4. https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B-NVFP4 |
| LFM2.5-24B-A2B | `LiquidAI/LFM2.5-24B-A2B` | Not cached | https://huggingface.co/LiquidAI/LFM2.5-24B-A2B |
| Nemotron 3.5 Lightning | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` | Not cached | https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4 |
| Mellum 2.1 | `JetBrains/Mellum2.1-12B-A2.5B-Thinking` and `JetBrains/Mellum2.1-12B-A2.5B-Thinking-GGUF` | Not cached | https://huggingface.co/JetBrains/Mellum2.1-12B-A2.5B-Thinking |
| GPT-OSS-20B | `openai/gpt-oss-20b` | Not cached | May require accepting the license on Hugging Face. |
| KAT-Coder-V2.5-Dev | `Kwaipilot/KAT-Coder-V2.5-Dev` | Not cached | Quantized path still to be verified. |
| Flint | `RecursiveSI/flint` | Not cached | Prefer a quantized checkpoint over BF16. |
| Qwen3.8-27B | `Qwen/Qwen3.8-27B` | Not cached | Dense quality comparison, not the throughput hypothesis. |
| Qwen3.8-Flash-Next | `Qwen/Qwen3.8-Flash-Next` | Not cached | Download only after a fitting quantized checkpoint is confirmed. |

Qwen3.7 was not searched as a local weight download. The assignment states it was API-only, and no official local checkpoint was required to start the GB10 runs.

## Engines

- llama.cpp commit `31288c9c66e59377f7788d920678a565bb89dd37` (`b11723`), CUDA build `build-no-vmm`, `GGML_CUDA_NO_VMM=ON`, `CMAKE_CUDA_ARCHITECTURES=121a-real`, `GGML_CUDA_FA=ON`.
- vLLM image requested: `docker://vllm/vllm-openai:v0.28.0` for `linux/arm64`, which is the version cited by the vLLM GB10 recipe measurement on 2026-08-31. The official model card also mentions `vllm/vllm-openai:nightly`; that tag is the fallback if 0.28.0 rejects the checkpoint.
