# Leaderboard

All figures were measured on `scholar-k061`, NVIDIA GB10, driver 595.71.05, job 480649. Nothing here is copied from a published DGX Spark score.

## Best measured serving configuration

Qwen3.6-35B-A3B NVFP4, vLLM 0.28.0, CUDA graphs, Marlin target MoE, Triton MTP MoE, **3 draft tokens**, FlashInfer, FP8 KV, eager safetensors load from node-local NVMe, context 131072, `--gpu-memory-utilization 0.26`.

Round 2, 27 October 2026. Profile A (~1045 in / 512 out) and profile B (~8225 in / 1024 out), MTP 3, engine active count equal to the client count:

| Profile | Clients | Utilization | Aggregate tok/s | Per-request tok/s | TTFT p50 |
|---|---:|---:|---:|---:|---:|
| A | 8 | 0.32 | 378.8 | 48.8 | 0.47 s |
| A | 12 | 0.32 | 466.0 | 39.6 | 0.77 s |
| A | 16 | 0.32 | 525.8 | 33.8 | 0.86 s |
| A | 24 | 0.45 | 580.7 | 25.3 | 1.26 s |
| B | 4 | 0.32 | 213.8 | 56.9 | 1.49 s |
| B | 8 | 0.32 | 302.0 | 40.0 | 1.50 s |
| B | 12 | 0.32 | 367.5 | 32.4 | 2.73 s |
| B | 16 | 0.32 | 411.4 | 27.4 | 2.90 s |
| B | 24 | 0.45 | 374.8 | 16.2 | 17.0 s |

Short prompts peaked at 24 active clients (581 tok/s). Thirty-two offered clients ran only 14 sequences and fell to 465 tok/s. The 8k profile peaked at 16 (411 tok/s). One 118k prompt decodes at 110 tok/s with MTP 3 and 53 tok/s with MTP off.

Aggregate output tokens/sec is completed completion tokens divided by the closed-loop wall time, including prefill. Output length was held with `min_tokens`/`ignore_eos` when the server accepted them; actual counts are below.

| Profile | Clients | Completed | Failed | Aggregate tok/s | TTFT p50 | Mean input tokens |
|---|---:|---:|---:|---:|---:|---:|
| A ~1k in / 512 out | 1 | 9 | 0 | 74.1 | 0.19 s | 1042 |
| A | 4 | 24 | 0 | 185.7 | 0.61 s | 1043 |
| A | 8 | 32 | 0 | 264.3 | 1.13 s | 1044 |
| A | 12 | 36 | 0 | 282.7 | 1.43 s | 1044 |
| B ~8k in / 1024 out | 1 | 4 | 0 | 67.9 | 1.27 s | 8223 |
| B | 4 | 12 | 0 | 154.7 | 2.99 s | 8224 |
| B | 8 | 16 | 0 | 214.9 | 2.77 s | 8225 |
| B | 12 | 24 | 0 | 236.8 | 2.78 s | 8225 |

Profile A is near saturation at 12 clients (8 to 12 gained about 7%). Profile B was still rising from 8 to 12 (about 10%). GPU utilization during the A c=8 run was about 96%.

The same server with `--enforce-eager` produced about 11 tok/s per stream and scaled linearly to 115 tok/s at 12 clients on profile A, with GPU utilization still near 21%. CUDA graphs are the difference.

## Speed reference: Qwen3.5-2B Q4_K_M, llama.cpp

Single-sequence decode 148.4 tok/s at short context, 77.6 tok/s with ~120k tokens already in the cache. Aggregate random-token decode peaks at **895 tok/s** (16 x 1024/256) and **554 tok/s** (12 x 8192/256). Chat serving peaks at **453 tok/s** on profile A at 12 clients and **336 tok/s** on profile B at 12 clients. Sixteen concurrent 8k chats overflow a 131072 KV pool and collapse to 11 tok/s.

This model is faster than Qwen3.6 and is not the quality choice.

## Qwen3.6 GGUF

UD-Q4_K_M does not load on this driver with the existing no-VMM llama.cpp build. CUDA aborts during weight upload.

## Not measured on this allocation

Ornith, LFM2.5, Nemotron, Mellum, GPT-OSS, and a filled 120k request were still pending when this table was written. A long-prompt retrieval run was queued after the graph sweep.
