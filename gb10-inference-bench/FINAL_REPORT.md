# GB10 inference benchmark

Measured on Purdue Scholar job `480649`, node `scholar-k061.rcac.purdue.edu`, 25 October 2026. The local workstation used to drive SSH is an RTX 2060 and was not used for inference.

## Executive summary

The best configuration measured on this GB10 is **Qwen3.6-35B-A3B NVFP4 served by vLLM 0.28.0 with CUDA graphs, Marlin for the NVFP4 experts, Triton for the MTP draft MoE, FlashInfer attention, FP8 KV, and 3 MTP draft tokens**.

The highest Qwen aggregate is **581 tok/s** on profile A (~1,045 input tokens, 512 output tokens) at **24 active clients**, MTP 3, `--gpu-memory-utilization 0.45`, `--max-num-seqs 24`. GPT-OSS-20B MXFP4 reached **1,184 tok/s** at 96 active clients on that profile, and **637 tok/s** at 64 active clients on 8k prompts. See Round 7. On that same Qwen server, a 32-client run reached only **465 tok/s**, and the engine’s running-request metric peaked at **14** while **24** requests waited. Thirty-two sequences at 0.45 left only 328,531 KV tokens, so the extra clients were queued. Forty and 48 were not run.

On profile B (~8,225 input tokens, 1,024 output tokens) the peak is **411 tok/s at 16 clients**. Twenty-four clients fell to **375 tok/s**.

A global `--moe-backend marlin` together with `--spec-method mtp` fails: the MTP head is unquantized and Marlin rejects it. The working form is the model-card split: Marlin for the target, and `speculative-config` with `moe_backend: triton` for the draft.

Round 4, jobs `481526` (scholar-k077) and `481532` (scholar-k078), 27 October 2026:

1. Four long contexts do decode together under MTP 3. The working server is utilization **0.55**, `--max-num-seqs 24`, KV pool **3,329,569 tokens**. Four prompts of 118,159–118,162 tokens, 1,024 forced output tokens each: all four finished, all four codes were retrieved, `num_requests_running` reached **4**, and KV-cache usage peaked at **0.247** (about 820k tokens occupied in a 3.33M pool). Per-request decode fell from the single-stream **110 tok/s** to **22.8 tok/s**.
2. Against MTP off on the same four-request workload, with `num_requests_running` also reaching 4: MTP 3 aggregate decode was **29.7 tok/s** versus **27.2 tok/s**. Per-request decode was **22.8 versus 13.6 tok/s**. End-to-end output was **22.6 versus 21.8 tok/s** over about 182–188 seconds, because prefill still dominates.
3. Nemotron 3.5 Lightning NVFP4 did serve without DSpark, at `--max-num-seqs 4`. Short-prompt aggregate peaked at **191 tok/s** with 4 sequences active and 12 waiting. That is well under Qwen’s 581. Raising the cap to 16 sequences crashed during KV allocation. DSpark was not retried. LFM2.5-24B-A2B FP8 served at 16 active sequences and peaked at **217 tok/s**, also well under Qwen.
4. On 10 harder checked tasks, Qwen3.6 with thinking disabled passed **7/10** in 19.6 seconds of generation (**21.4** successes/minute). The same model with server-default thinking passed **5/10** in 233 seconds (**1.28**/minute) and spent 16,295 of 17,387 completion tokens on reasoning. Qwen3.5-2B, reasoning off, passed **4/10** in 11.9 seconds (**20.2**/minute). With thinking off, the 35B solves the discount bug, shortest path, and Go median that the 2B misses, at almost the same success rate per minute. With thinking on, it does not.
5. Short prompts: Qwen3.6 MTP 3, 24 clients, utilization 0.45, **581 tok/s**. Eight-k prompts: same model, 16 clients, utilization 0.32, **411 tok/s**. Long contexts, one request: MTP 3 at about **110 tok/s**. Long contexts, four resident requests: MTP 3 at utilization 0.55, **22.8 tok/s per request** and **29.7 tok/s** aggregate decode.
6. GPT-OSS-20B MXFP4 with reasoning low is the fastest server measured: **1,184 tok/s** at 96 active clients on 1k prompts, and **637 tok/s** at 64 active clients on 8k prompts. Low reasoning scored **7/10** in 98 seconds (**4.3** successes/minute), the same pass count as Qwen thinking-off and slower. Qwen remains faster for finished coding tasks and for a single 118k stream.

Four simultaneous prompts of about **120,200 tokens** each completed with the passphrase retrieved on every request, for both MTP 3 and MTP off. That is demonstrated concurrency, not just a KV-capacity quote.

Ornith 1.5 with one MTP draft token stayed slower than Qwen3.6 MTP 3: 399 vs 466 tok/s at 12 clients on profile A, and 294 vs 367 tok/s on profile B.

Qwen3.5-2B Q4_K_M under llama.cpp is much faster (up to **895 tok/s** aggregate random-token decode, **453 tok/s** on the short chat profile) and is the speed reference, not the model to use for coding agents.

`--enforce-eager` on the same Qwen3.6 checkpoint dropped decode to about **11 tok/s per stream**. CUDA graphs are required.

The existing llama.cpp build cannot load the Qwen3.6 UD-Q4_K_M GGUF on driver 595.71.05. It aborts during CUDA weight upload.

## Round 4: resident long-context decode

The earlier MTP 3 pool of 287,677 tokens was not a property of MTP itself. vLLM sizes the pool from `free memory before the process minus free memory after the profile`, then adds peak-activation headroom. CUDA graph storage was 0.10–0.46 GiB in every MTP 3 log and does not explain the cliff. The weights are 21.97 GiB. What changed was the profiler’s “consumed” figure:

| When | Utilization | max-num-seqs | Consumed (weights + non-torch) | KV tokens | Free memory after startup |
|---|---:|---:|---:|---:|---:|
| Earlier 24-client run | 0.45 | 24 | 22.5 GiB | 2,403,554 | 68.5 GiB |
| This round, first start | 0.45 | 24 | 49.87 GiB | 333,637 | 96.7 GiB |
| This round, retry | 0.55 | 24 | 22.64 GiB | 3,329,569 | 68.3 GiB |
| MTP off, this round | 0.45 | 4 | (not the 50 GiB case) | 938,399 | — |

The 49.87 GiB figure was not still allocated when the server finished starting: 96.7 GiB was free. The KV size had already been frozen from the pessimistic snapshot. The same 24-sequence capture schedule (piecewise graphs up to 192) produced both 333k and, on the earlier run, 2.40M tokens. Raising utilization from 0.45 to 0.55 on the next clean start profiled the real ~23 GiB footprint and left 3.33 million tokens, 25.4 full contexts of 131,072.

That 0.55 server ran the four-request measurement. Prompts were 118,160, 118,162, 118,159, and 118,160 tokens. Each request was forced to 1,024 output tokens. All four completed and all four retrieval codes were in the output.

| Mode | KV tokens | running max | KV usage max | Decode tok/s per request | Aggregate decode tok/s | Prefill tok/s | End-to-end tok/s | Wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MTP 3, util 0.55, seqs 24 | 3,329,569 | 4 | 0.247 | 22.78 | 29.65 | 1,458 | 22.56 | 181.6 s |
| MTP off, util 0.45, seqs 4 | 938,399 | 4 | 0.925 | 13.59 | 27.23 | 1,659 | 21.81 | 187.8 s |

`num_requests_waiting` also peaked at 3 on both runs, which is the chunked prefill queue before all four were admitted. The decode rates are the overlap evidence: single-stream MTP 3 is 110 tok/s and single-stream MTP off is 53 tok/s, and both fell once four requests were in the engine. MTP 3 remains the faster long-context decoder per request. The aggregate gap is small because each request is only 1,024 generated tokens after a 118k prefill.

The 22.8 and 29.7 figures are two definitions on the same four MTP 3 requests, not a missing 7 tok/s. Clocks are seconds from the shared start. Each request produced 1,024 tokens. Per-request decode is the mean of `(1024-1)/(latency-ttft)`:

| Request | TTFT | Finish | Time after first token | Tokens/s |
|---|---:|---:|---:|---:|
| 2 | 43.42 | 179.48 | 136.07 | 7.52 |
| 1 | 82.94 | 179.23 | 96.29 | 10.62 |
| 3 | 123.06 | 180.03 | 56.98 | 17.95 |
| 0 | 162.94 | 181.54 | 18.60 | 55.01 |

The mean of those four rates is **22.78**. The early request’s long post-TTFT interval overlaps the later prefills, so that interval is stalled time, not a steady 7.5 tok/s decode. The last request, which starts generating after the others have already been in flight, finishes 1,024 tokens in 18.6 seconds.

Aggregate decode divides all **4,096** completion tokens by one window, from the earliest TTFT (43.42 s) to the latest finish (181.54 s), which is 138.13 s. `4096/138.13 = 29.65`. That window contains overlapping generation, so it is higher than the mean of the four unequal per-request rates. It is lower than four times a single-stream 110 tok/s because the requests were staggered by chunked prefill. Subtracting the first token inside the per-request formula, and not in the window formula, changes the window by about 0.1 percent and does not explain the gap.

The earlier MTP-off pool of 2,737,315 tokens was a larger allocation at the same 0.45 / 4-sequence setting. This round’s 938,399 tokens was still enough: usage peaked at 92.5% and all four contexts stayed resident.

## Nemotron 3.5 Lightning

LFM2.5-24B-A2B’s published NVFP4 checkpoints ask for vLLM 0.31. Nemotron has an NVIDIA GB10 recipe on vLLM 0.27.1: Marlin MoE, FP8 KV, FlashInfer Mamba, and the DSpark drafter `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4-DSpark`. That is the one architecture added. Both checkpoints were downloaded. `config.json` reports `model_type: nemotron_h`, architecture `NemotronHForCausalLM`, and `max_position_embeddings: 1048576`, so 128k is inside the native window. The bench set `--max-model-len 131072`.

vLLM 0.28.0 selected speculative method `dspark` from the drafter path and set the Mamba cache dtype to float32. It did not finish startup:

- Utilization 0.80 on scholar-k077, while the previous server’s memory was still held: free memory 29.04 GiB, requested 99.03 GiB.
- Utilization 0.70 on a later job: free memory 64.42 GiB, requested 86.65 GiB.
- Utilization 0.45: the profile succeeded, **9,834,999** KV tokens (75× a 131k context), then `torch.AcceleratorError: CUDA error: an illegal memory access was encountered` inside KV-cache initialization. The log immediately before that had warmed the Mamba2 SSD Triton kernels and compiled the DSpark head. The CUDA error is reported asynchronously, so the Python stack points at cache initialization rather than a specific kernel.

No throughput number was measured on that DSpark configuration.

### Nemotron without DSpark

The next start removed the drafter. Flags: vLLM 0.28.0, CUDA graphs left on, `--max-num-seqs 4`, `--max-model-len 131072`, `--gpu-memory-utilization 0.38` chosen so that 0.38×123.79 GiB stayed under the 64 GiB CUDA free memory measured before launch, `--mamba-ssm-cache-dtype float16`, FlashInfer Mamba, Marlin MoE, FP8 KV, eager safetensors from local NVMe. No 1M cache was requested. A one-token smoke test returned `pong` with zero reasoning tokens.

That server allocated **6,920,601** KV tokens (52.8× a 131,072 context) and 22.5 GiB of KV. Weights plus non-torch memory were about 21 GiB.

| Profile | Clients | Aggregate tok/s | Per-request tok/s | TTFT p50 | Active | Waiting | Completed |
|---|---:|---:|---:|---:|---:|---:|---:|
| A, ~1032 in / 512 out | 1 | 82.2 | 82.2 | 0.19 s | 1 | 0 | 10/10 |
| A | 8 | 192.5 | 27.3 | 10.9 s | 4 | 4 | 28/28 |
| A | 16 | 191.1 | 17.6 | 32.4 s | 4 | 12 | 36/36 |
| B, ~8172 in / 1024 out | 8 | 162.7 | 25.1 | 27.4 s | 4 | 5 | 16/16 |
| B | 16 | 179.4 | 19.7 | 58.9 s | 4 | 13 | 24/24 |
| one 118,199-token prompt, 1024 out | 1 | 25.6 end-to-end | 75.2 decode | 26.4 s | 1 | 0 | 1/1, code retrieved |

Qwen’s matching peaks are 581 tok/s (short, 24 active) and 411 tok/s (8k, 16 active), and 110 tok/s decode on one 118k context. Nemotron is slower at every one of those points. Eight and sixteen clients did not raise throughput past the four-sequence cap.

`--max-num-seqs 16` on the same flags computed a KV pool of 13,766,304 tokens and then died with `CUDA error: an illegal memory access` inside `torch.zeros` while allocating that pool. The log just before the fault had finished the Mamba2 SSD Triton warmup and selected the FlashInfer Mamba SSU backend. The Python stack is the allocation call; the runtime says the fault may have been reported late. The same configuration was not launched again. A relaunch of the working 4-sequence server in that same job, and an 8,192-token diagnostic with `CUDA_LAUNCH_BLOCKING=1`, also faulted, so the device stayed unusable until the job ended. The table above is from a later job that started clean at 4 sequences. vLLM 0.27.1 was not needed for the serving result and was not used for the measurement. DSpark was not turned back on: 191 tok/s is not close to 581.

Thinking off, the same 10-task suite, temperature 0, 4,096-token budget: **6/10**, 1,135 completion tokens, 15.8 seconds, **22.8** successes/minute, about **1,370** successful tasks per GPU-hour if the GPU runs one task at a time. It passed edit distance, longest increasing subsequence, the dropped-record fix, shortest path, JavaScript grouping, and Go median. It missed the discount bug, which Qwen thinking-off passed, and it missed the invoice, the lock, and the tool-plan JSON, which Qwen also missed. It did not solve any task Qwen thinking-off missed.

## LFM2.5-24B-A2B

The vendor FP8 checkpoint `LiquidAI/LFM2.5-24B-A2B-FP8` loads in the existing vLLM 0.28.0 image. The server resolved `Lfm2MoeForCausalLM`. `max_position_embeddings` is **131072**, and the bench set `--max-model-len 131072`, so the native window covers 128k. A separate image was not required.

The first launch asked for utilization 0.45 while CUDA free memory was 54.03 GiB, short of the 55.7 GiB gate. The retry measured free memory and used utilization **0.40** with `--max-num-seqs 16`, FP8 KV, chunked prefill, and prefix caching. It allocated **1,885,946** KV tokens, 14.4 full contexts of 131,072. Sixteen short or 8k requests fit in that pool.

| Profile | Clients | Aggregate tok/s | Per-request tok/s | TTFT p50 | Active | Waiting | Completed |
|---|---:|---:|---:|---:|---:|---:|---:|
| A, ~1020 in / 512 out | 1 | 55.8 | 55.8 | 0.27 s | 1 | 0 | 7/7 |
| A | 8 | 155.2 | 19.4 | 0.77 s | 8 | 0 | 24/24 |
| A | 16 | 217.5 | 13.6 | 0.75 s | 16 | 0 | 32/32 |
| B, ~8203 in / 1024 out | 8 | 128.4 | 20.7 | 2.23 s | 8 | 5 | 12/12 |
| B | 16 | 199.4 | 12.5 | 1.08 s | 16 | 6 | 16/16 |

Sixteen clients were genuinely active on the short profile. The 8k profile kept 16 running and also queued. Both peaks are under half of Qwen’s. No long-context decode and no coding suite were run. There is no sign that more tuning would close a gap this large, and the model was not given a second quantization.

Neither Nemotron nor LFM is a better speed/quality balance than Qwen3.6 with thinking off. Nemotron’s serial coding rate is similar and its pass count is lower. Its serving rate is about one third of Qwen’s. LFM is slower still and was not worth the quality suite.

## Round 6: GPT-OSS-20B and Mellum2.1

Jobs on `scholar-k077`, 28 October 2026. vLLM 0.28.0. CUDA graphs stayed on. Weights were copied to the job-private `/tmp` and loaded with `--safetensors-load-strategy eager`.

### GPT-OSS-20B

Checkpoint `openai/gpt-oss-20b`, architecture `GptOssForCausalLM`, `quant_method: mxfp4`, `max_position_embeddings: 131072`. The served model used about 16.5 GiB. FlashInfer’s TRTLLM MXFP4+MXFP8 MoE kernel refused this GPU (`kernel does not support current device`). The run used vLLM’s default MXFP4 path, `--attention-backend flashinfer`, `--kv-cache-dtype fp8`, `--max-num-seqs 64`, `--max-model-len 131072`, `--max-num-batched-tokens 8192`, chunked prefill, prefix caching, and `--tool-call-parser openai`.

CUDA free memory on this platform ignores reclaimable file cache. A 60 GiB anonymous allocation was used to drop that cache before the startup check. The short-prompt server used utilization **0.38** and reported **2,329,685** KV tokens (17.8 full contexts of 131,072). The 8k server was a later start at utilization **0.36** with **2,127,572** KV tokens.

Harmony formatting is the model’s own chat template. The compute node could not download the Harmony vocab, so `o200k_base.tiktoken` and `cl100k_base.tiktoken` were stored under `encodings/` and the server was started with `TIKTOKEN_ENCODINGS_BASE=/encodings`. With system text `Reasoning: low`, `17+4` returned content `21` and a short reasoning string. A tool request returned `get_weather` with `{"city":"Paris"}`.

Speed runs used `Reasoning: low`, temperature 0, and a forced output length, so the tok/s figures are generated completion tokens, not input plus output. The API reported `reasoning_tokens: 0` on those runs.

| Profile | Clients | Aggregate tok/s | Per-request tok/s | TTFT p50 | Active | Waiting | Completed |
|---|---:|---:|---:|---:|---:|---:|---:|
| A, ~1088 in / 512 out | 1 | 48.1 | 48.1 | 0.21 s | 1 | 0 | 6/6 |
| A | 8 | 219.5 | 27.5 | 0.94 s | 8 | 0 | 32/32 |
| A | 16 | 368.1 | 23.0 | 1.09 s | 16 | 0 | 48/48 |
| A | 32 | 617.2 | 19.3 | 1.95 s | 32 | 4 | 96/96 |
| A | 64 | 1,012.6 | 15.9 | 3.59 s | 64 | 8 | 128/128 |
| B, ~8271 in / 1024 out | 1 | 45.8 | 45.8 | 1.09 s | 1 | 0 | 3/3 |
| B | 8 | 176.5 | 22.1 | 5.77 s | 8 | 4 | 16/16 |
| B | 16 | 271.5 | 18.1 | 3.13 s | 16 | 6 | 30/30 |
| B | 32 | 409.3 | 12.9 | 4.21 s | 32 | 14 | 32/32 |

One prompt of **118,695** tokens, reasoning low, 1,024 forced output tokens: the retrieval code was returned, prefill was **3,076 tok/s**, and decode was **37.2 tok/s**.

`--max-num-seqs 128` was tried twice. Both died during memory profiling because free memory rose while vLLM was sampling it (`Initial free memory` about 51–53 GiB, `current free memory` about 61 GiB). That is the file cache being reclaimed, not an illegal kernel launch. 96, 192, and 256 clients were not measured. At 64 clients every request was active and throughput was still rising, so 1,013 tok/s is not a demonstrated peak.

Medium reasoning, the same 10-task suite, temperature 0, 4,096-token budget: **8/10**, 4,919 completion tokens, 101 seconds, **4.75** successes/minute, **285** successful tasks per GPU-hour. The API again reported zero reasoning tokens; the extra time and tokens relative to Qwen’s thinking-off run are the reasoning text in the reply. It passed every task Qwen thinking-off passed, plus the invoice (1,687 cents). It missed the lock state machine and the tool-plan JSON, which Qwen also missed. High reasoning was not run.

### Mellum2.1

Checkpoint `JetBrains/Mellum2.1-12B-A2.5B-Thinking`, architecture `MellumForCausalLM`, BF16, `max_position_embeddings: 131072`. vLLM 0.28.0 loaded it with `--reasoning-parser qwen3`, `--max-model-len 131072`, `--max-num-seqs 32`, utilization **0.39**. Weights were **22.77 GiB**. The profiler then charged **37.4 GiB** consumed, leaving **531,539** KV tokens, 4.1 full contexts of 131,072. One 118k prompt fits. Thirty-two short prompts fit. An earlier start at utilization 0.28 had a negative KV budget and was not repeated. The GGUF and its MTP head were not run; the BF16 server was already well below the short-prompt leaders.

Thinking stayed on. Under the forced 512- and 1,024-token budgets, `reasoning_tokens` accounted for essentially every completion token. The tok/s below are generated tokens, and they are thinking tokens.

| Profile | Clients | Aggregate tok/s | Active | Waiting | Reasoning tokens |
|---|---:|---:|---:|---:|---:|
| A, ~1044 in / 512 out | 1 | 44.6 | 1 | 0 | 3,066 of 3,072 |
| A | 8 | 157.6 | 8 | 0 | 12,264 of 12,288 |
| A | 16 | 238.7 | 16 | 0 | 16,352 of 16,384 |
| A | 32 | 356.2 | 32 | 7 | 32,704 of 32,768 |
| B, ~8224 in / 1024 out | 8 | 131.7 | 8 | 5 | 8,184 of 8,192 |
| B | 16 | 197.5 | 16 | 5 | 16,368 of 16,384 |

One prompt of **118,183** tokens, 256 forced output tokens: the code was retrieved, prefill was **4,813 tok/s**, decode was **34.8 tok/s**.

The 10-task suite, thinking left on, temperature 0, 4,096-token budget: **8/10**, 12,076 completion tokens of which **10,972** were reasoning tokens, 267 seconds, **1.80** successes/minute, **108** successful tasks per GPU-hour. Same pass pattern as GPT-OSS medium: the invoice passed, the lock and the tool plan failed. The discount task used the entire 4,096-token budget and still passed.

### What to run

Short prompts, aggregate generated tokens: GPT-OSS-20B, reasoning low, 64 active clients, **1,013 tok/s**. That is the highest measured point, and it is not saturated.

Eight-k prompts: Qwen3.6 MTP 3 at 16 clients, **411 tok/s**. GPT-OSS reached **409 tok/s** at 32 active clients and was still climbing, so this ranking can change if 64 clients are measured on the working server.

One long stream: Qwen3.6 MTP 3, about **110 tok/s**. GPT-OSS was **37 tok/s** and Mellum **35 tok/s** on a filled ~118k prompt.

Coding pass count: GPT-OSS medium and Mellum thinking, **8/10**. Coding speed: Qwen3.6 with thinking off, **21.4** successes/minute. Qwen remains the better balance when the goal is finished coding tasks per hour. GPT-OSS is the better balance when the goal is short-prompt serving throughput, with a higher pass count if the extra minute per task is acceptable.

The single next measurement is GPT-OSS profile B at 96 clients on the working 96-sequence server. Forty-eight clients scored 400 tok/s and 64 scored 637, so the 8k curve had not flattened. Short-prompt 128-sequence starts still fail when free memory rises during profiling.

## Round 7: GPT-OSS past 64 clients

Job `481771` on `scholar-k077`. Same vLLM 0.28.0 MXFP4 server as Round 6: FlashInfer attention, FP8 KV, CUDA graphs, Harmony vocab from local tiktoken files, `Reasoning: low`.

The 128-sequence failures were not a CUDA kernel fault. vLLM asserts that free memory must not rise during its startup profile. Killing a server and starting another lets file cache come back, so free memory climbed from about 51 GiB to about 61 GiB and the assert fired. A fresh job evicted 40 GiB of cache, waited until two CUDA free readings were within 2 GiB (52.3 GiB then 51.7 GiB), and launched **96** sequences at utilization **0.25**. That start succeeded. CUDA graphs were 0.29 GiB actual (piecewise captures up to 1,024 tokens, full graphs up to 96). Weights plus non-torch memory were 16.23 GiB. The KV pool was **1,076,566** tokens.

| Profile | Clients | Aggregate tok/s | Per-request tok/s | TTFT p50 | Active | Waiting | Completed |
|---|---:|---:|---:|---:|---:|---:|---:|
| A, ~1088 in / 512 out | 96 | 1,183.5 | 12.5 | 6.12 s | 96 | 68 | 192/192 |
| B, ~8271 in / 1024 out | 48 | 400.0 | 8.4 | 27.8 s | 48 | 46 | 48/48 |
| B | 64 | 637.2 | 10.0 | 1.04 s | 64 | 13 | 64/64 |

Ninety-six short-prompt clients were all active and raised throughput from 1,013 to **1,184 tok/s**. The waiting peak was 68, and first-token time rose from 3.6 s at 64 clients to 6.1 s, so 128 was not started. On 8k prompts, 48 clients were active but queued heavily (TTFT 28 s, 400 tok/s, just under Qwen). Sixty-four clients were active with a waiting peak of 13 and TTFT 1.0 s, at **637 tok/s**. That is above Qwen’s **411 tok/s**. The 8k series was still rising from 48 to 64. No failures.

Low reasoning, the same 10 tasks, temperature 0, 4,096-token budget: **7/10**, 4,796 completion tokens, the API counted **0 reasoning tokens**, 98.5 seconds, **4.26** successes/minute. It passed the invoice and missed the discount bug. Medium reasoning had been **8/10** in 101 seconds, including the discount bug. Low reasoning matches Qwen’s pass count and does not match Qwen’s speed (19.6 seconds, 21.4 successes/minute).

The same ten tasks with four in flight at a time, low reasoning, natural completions: **8/10** in **68.5** seconds of wall time, **7.0** successes per wall-clock minute. That is still well under Qwen’s serial rate.

Two prompts of 118,697 and 118,696 tokens, 1,024 output tokens each, reasoning low: both codes were retrieved, `num_requests_running` reached **2**, KV usage peaked at **0.21**, per-request decode was **22.2 tok/s**, and aggregate decode was **29.8 tok/s**. Prefill was 2,068 tok/s. They overlapped. A single GPT-OSS 118k stream was 37 tok/s, and Qwen’s single stream is about 110.

Short prompts: GPT-OSS, reasoning low, 96 clients when a 6 s first token is acceptable, otherwise 64 clients at 1,013 tok/s with a 3.6 s first token. Eight-k prompts: GPT-OSS, reasoning low, 64 clients, 637 tok/s. One long stream: Qwen3.6 MTP 3. Finished coding tasks per minute: Qwen3.6 with thinking off. The 8k curve past 64 clients is measured in Round 8.

## Round 8: warm 8k scaling, and the Harbor blocker

Job `481803` on `scholar-k077`. Same GPT-OSS server shape as the Round 7 96-sequence start: vLLM 0.28.0, MXFP4, FlashInfer, FP8 KV, CUDA graphs 0.3 GiB, utilization 0.25, `--max-num-seqs 96`, KV pool **1,072,588** tokens. One single-stream 8k request was run first so the timed waves were not the server’s first long prefill. Reasoning effort low. Zero failures.

| Clients | Order | Aggregate tok/s | Per-request tok/s | TTFT p50 | TTFT p95 | p95 latency | Active | Waiting |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 64 | first multi-client wave | 452.0 | 7.1 | 34.0 s | 61.0 s | 144.9 s | 64 | 60 |
| 48 | after that wave | 643.4 | 13.5 | 0.87 s | 1.22 s | 76.3 s | 48 | 0 |
| 80 | next | 746.4 | 9.4 | 1.19 s | 17.0 s | 109.6 s | 80 | 13 |
| 96 | next | 816.7 | 8.6 | 1.39 s | 17.0 s | 120.2 s | 96 | 13 |

The Round 7 jump from 400 tok/s at 48 clients to 637 tok/s at 64 clients does not reproduce as a concurrency effect. It reproduces as a first-batch effect. In Round 7 the 48-client run was the first 8k wave and had a 28 second first token and 46 requests waiting. The 64-client run was the next wave. This round, with 64 as the first multi-client wave, that run was the slow one (452 tok/s, TTFT 34 s, 60 waiting). The following 48-client run, on the same server, was 643 tok/s with a 0.87 second first token and no queue. After that, 80 and 96 stayed in the warm regime and throughput kept rising, with every offered client active and a waiting peak of 13. The highest stable 8k point is **817 tok/s at 96 active clients**. 128 was not tried. Qwen’s 8k peak remains **411 tok/s**.

## Real Coding-Agent Benchmark — 12 Tasks

The evaluation entry point is `scripts/eval-host`, which grades through `scripts/harbor-run` (Harbor 0.24.0, dataset `swebenchpro`, agent OpenCode). Task choice is `--include-task-name`. The project’s listing function, `list_dataset_task_names`, returns Harbor’s default order. The 12 tasks below are that function’s first 12 names. They were not reordered or filtered. `swebench_release` stays unverified, which is the project rule until a live Harbor run records the release. The list is in `raw/swebenchpro-12.txt`.

| Model | Reasoning | Load | Tasks Passed | Total Time | Tasks/min | Avg Tokens/Task | Background tok/s |
|---|---|---|---|---|---|---|---|
| Qwen3.6 NVFP4 MTP3 | thinking off | none | 5/12 | 115.3 min | 0.043 | 18,199 out | — |
| GPT-OSS-20B MXFP4 | low | none | not run | | | | |
| GPT-OSS-20B MXFP4 | medium | none | 0/12 | 65.0 min | 0 | 8,405 out | — |
| Qwen3.6 NVFP4 MTP3 | thinking off | 8k background | not run | | | | |
| GPT-OSS-20B MXFP4 | medium | 8k background | 1/12 | 161.7 min | 0.006 | 6,634 out | 236 |

Qwen ran unloaded on job `481918`, scholar-k077, vLLM 0.28.0, MTP 3, FP8 KV, Marlin target, Triton MTP, FlashInfer. The server that graded these tasks used utilization 0.46 and a KV pool of 2,495,474 tokens. Thinking was off on every call (`chat_template_kwargs.enable_thinking: false`, and the same default on the server). OpenCode used `/v1/chat/completions` through a local proxy. The built-in OpenAI provider’s `/v1/responses` path was not used: vLLM 0.28 rejects the tool-result follow-up. The first two tasks ran one at a time. The other ten ran two at a time. Wall time is the union of the twelve trial intervals, 6,918 seconds. Tasks/min and tasks/GPU-hour count verifier passes, not attempts: 5 / 115.3 min = 0.043 per minute, and 2.60 per GPU-hour. Harbor’s summed prompt tokens were 50,141,494. Completion tokens were 218,386, about 18,199 per task. Two requests hit the 131,072-token context limit. No verifier timeout. One of those two context-limit trials still scored 1 (vuls `78b52d6`). The other scored 0 (the second qutebrowser instance).

Passes, in selection order: qutebrowser `2e96108` 1, flipt `b68b896` 0, qutebrowser `01d1d14` 0, vuls `78b52d6` 1, flipt `e42da21` 0, nodebb `84e0657` 0, element-web `f3534b4` 1, navidrome `d8e7943` 0, vuls `f0b3a8b` 1, vuls `6eff6a9` 1, openlibrary `fdbc0d8` 0, ansible `b2a289d` 0. A one-task gap against another model would not be a ranking. The 5-to-0 gap is larger than that. GPT-OSS medium, same 12 tasks, same agent, unloaded, job `481931` on scholar-k078: 0/12. The agent edited files (tool calls and edits are in the trajectories) and every verifier returned 0. No agent exception and no verifier timeout. Wall time is the union of the trial intervals, 3,899 seconds. Completion tokens were 100,860, about 8,405 per task. Prompt tokens summed by Harbor were 15,518,379. Successful tasks per minute and per GPU-hour are 0.

The same 12 tasks were run again on that server with a 32-client 8k/1024 background (reasoning medium, `ignore_eos`). The server’s `--max-num-seqs` is 16, so the engine’s running count peaked at 16 and the waiting count peaked at 29. The background window was 7,320 seconds, 1,690 requests, 0 failures, aggregate 236 tok/s, TTFT p50 71.3 seconds, TTFT p95 79.1 seconds. A KV sample during that window was 4.4% of the 3,012,411-token pool. The agent run scored 1/12. The pass is qutebrowser `2e96108`, which Qwen also passed. Wall time is the union of the trial intervals, 9,701 seconds. Completion tokens were 79,605, about 6,634 per task. Harbor’s summed prompt tokens were 10,748,533. No agent exception and no verifier timeout. There were 146 tool calls whose name was not a real tool, including names with a leaked Harmony channel marker (`grep<|channel|>commentary`). One pass under load against zero passes unloaded is a one-task difference and is not a claim that the background helped.

GPT-OSS low was not run. Qwen under an 8k background was not run. The mixed 1k/8k/32k workload was not run. The allocation on scholar-k078 ended after the loaded GPT-OSS run.

Task ids, in selection order:

1. `instance_qutebrowser__qutebrowser-2e961080a85d660148937ee8f0f6b3445a8f2c01-v363c8a7e5ccdf6968fc7ab84a2053ac78036691d`
2. `instance_flipt-io__flipt-b68b8960b8a08540d5198d78c665a7eb0bea4008`
3. `instance_qutebrowser__qutebrowser-01d1d1494411380d97cac14614a829d3a69cecaf-v2ef375ac784985212b1805e1d0431dc8f1b3c171`
4. `instance_future-architect__vuls-78b52d6a7f480bd610b692de9bf0c86f57332f23`
5. `instance_flipt-io__flipt-e42da21a07a5ae35835ec54f74004ebd58713874`
6. `instance_nodebb__nodebb-84e065752f6d7fbe5c08cbf50cb173ffb866b8fa-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e`
7. `instance_element-hq__element-web-f3534b42df3dcfe36dc48bddbf14034085af6d30-vnan`
8. `instance_navidrome__navidrome-d8e794317f788198227e10fb667e10496b3eb99a`
9. `instance_future-architect__vuls-f0b3a8b1db98eb1bd32685f1c36c41a99c3452ed`
10. `instance_future-architect__vuls-6eff6a9329a65cc412e79b8f82444dfa3d0f0b5a`
11. `instance_internetarchive__openlibrary-fdbc0d8f418333c7e575c40b661b582c301ef7ac-v13642507b4fc1f8d234172bf8129942da2c2ca26`
12. `instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad`

On these 12 tasks, Qwen thinking-off produced 2.60 successful tasks per GPU-hour. The 10-task suite remains a different measurement: Qwen thinking-off at 21.4 per minute there, GPT-OSS medium at 4.7, GPT-OSS low at 4.3. The synthetic 8k question is answered: 817 tok/s at 96 active clients.

## Round 9: GPT-OSS tool names, and Qwen at 262K

### Tool-call corruption

The bad Harbor names, such as `read<|channel|>commentary`, are produced by the Harmony parser when the model emits the channel marker twice. A direct parse of `to=functions.read<|channel|>commentary<|channel|>commentary` on vLLM 0.28.0 returns recipient `functions.read<|channel|>commentary`. A single well-formed header, `to=functions.read<|channel|>commentary json`, returns recipient `functions.read`. The stock renderer already writes history in that legacy order (`assistant to=functions.get_weather<|channel|>commentary json`). vLLM 0.31’s `_use_legacy_tool_call_headers` rewrites the newer `channel` then `to=` order. This 0.28 build does not emit that newer order, so that rewrite does not apply here. Adding `--reasoning-parser openai_gptoss` was not the missing piece: the second launch died because GPU memory had not been released, and the header render does not depend on that flag.

The change that matches the doubled header is in `vllm/parser/harmony.py` `_normalize_recipient`. vLLM 0.28 already cuts a recipient at `<|constrain|>`. The patched file also cuts at the first `<|channel|>`. On the doubled header, the patched function returns `functions.read`, and the tool name is `read`. The patch is `patches/harmony_028_normalize_recipient.py`, bind-mounted over the image file. The vLLM 0.28 image was not modified.

A 12-turn auto tool loop, plain and streamed, did not emit `<|channel|>` in a tool name on the stock server or the patched server. One streamed response contained `<|end|><|start|>assistant` inside a concatenated name. Forced `get_weather` for 15 turns on the stock server stayed clean. The Harbor-sized failure is the doubled channel header, not the short loop.

### Three-task rerun

GPT-OSS medium, patched parser, no background load, job `482102` on scholar-k079. Same OpenCode agent and the same three tasks Qwen passed and GPT-OSS previously failed.

| Task | Before | This round |
|---|---|---|
| qutebrowser `2e96108` | 0, 102 tools, 33 invalid | 0, 45 tools, 5 invalid, 0 channel markers in tool names, 367 s, 8,132 completion tokens |
| vuls `78b52d6` | 0, 91 tools, 28 invalid | 0, 2 tools, 477 s, 132 completion tokens |
| element-web `f3534b4` | 0, 77 tools, 22 invalid | did not start |

The five invalid names on qutebrowser were `open_file`, `apply_patch`, `glob`, `search`, and `globbrowse`. None contained `<|channel|>`. On vuls the model wrote a raw Harmony header as assistant text (`<|start|>assistant<|channel|>commentary to=functions.search`) and stopped. No context-limit error. Element-web did not start because Docker’s credential helper failed (`error getting credentials`). That is an infrastructure failure, not a model score. A full 12-task GPT-OSS rerun is not justified: the channel marker is gone from tool names on the task that ran a full trace, and the pass count is still zero.

### Qwen at 262144

The two Round 8 context failures were not prompts past 131,072. Both were OpenCode requests with about 99,073 prompt tokens and `max_tokens` 32,000, which sum to 131,073. They were qutebrowser `01d1d14` (reward 0) and vuls `78b52d6` (reward 1 despite the error).

Job `482103` on scholar-k070. The first start at utilization 0.43 profiled only 1.06 GiB of KV and refused 262,144 (it estimated a maximum of 68,608). The retry on the same job, CUDA graphs left on, MTP 3, thinking off, FP8 KV, Marlin, FlashInfer, `--max-num-seqs 2`, got a KV pool of 300,135 tokens, 1.14 times one 262,144-token context.

| Task | Round 8 at 131072 | This round at 262144 |
|---|---|---|
| qutebrowser `01d1d14` | 0, context error | 1, no context error, max step input 105,787, 117 steps, 25,297 completion tokens, 697 s |
| vuls `78b52d6` | 1, same context error | 0, no context error, max step input 104,535, 123 steps, 28,587 completion tokens, 1,234 s |

The context-limit error is gone on both. The prompts stayed under 131,072. Raising the window removed the `prompt + max_tokens` rejection. It did not raise the pass count: one task flipped from 0 to 1, and the other flipped from 1 to 0.

Qwen thinking-off remains the model with measured Harbor passes: 5/12 and 2.60 successful tasks per GPU-hour on the Round 8 suite. GPT-OSS is still ahead on synthetic token rate and still at zero passes on the tasks rerun here.

## Round 10: OpenCode context handling

The 12-task Qwen run did not tell OpenCode the context limit. OpenCode 1.19.5 then reserved the default 32,000 output tokens. The two context errors in the logs are real: 99,073 prompt tokens plus that 32,000 reservation is 131,073. OpenCode compacted after the HTTP 400 and continued. Vuls `78b52d6` passed after that compaction. qutebrowser `01d1d14` continued and the verifier still failed. The other ten tasks never compacted. Their failures are verifier results, or an agent that stopped without tests, not overflow.

`scripts/run-harbor-12.sh` now sets `limit.context` 131072 and `limit.output` 8192. That change has not been re-run. MAGE is not connected to the Harbor agent. The full trace is `OPENCODE_HARBOR_CONTEXT_AUDIT.md`.

## Harder coding tasks

Ten tasks, temperature 0, `max_tokens` 4096. Python and JavaScript and Go answers were executed. JSON answers were parsed. The tasks are a basis-point discount bug split across a helper, longest increasing subsequence, a repository function that drops the last record, a lock state machine, Levenshtein distance, a two-call tool plan that must match a schema, undirected shortest path, a JavaScript group-and-sum, a Go lower-median, and an invoice in integer cents.

Thinking off sends `chat_template_kwargs.enable_thinking: false`. Thinking on is the server default with `--reasoning-parser qwen3`. The 2B server was llama.cpp `--reasoning off`.

| Run | Pass | Completion tokens | Reasoning tokens | Generation time | Successes per minute |
|---|---:|---:|---:|---:|---:|
| Qwen3.6, thinking off | 7/10 | 1,261 | 0 | 19.6 s | 21.4 |
| Qwen3.6, thinking on | 5/10 | 17,387 | 16,295 | 233 s | 1.28 |
| Qwen3.5-2B, thinking off | 4/10 | 1,472 | 0 | 11.9 s | 20.2 |

Tasks only the 35B passed, with thinking off: the discount bug, shortest path, and Go median. The 2B passed longest increasing subsequence, edit distance, the dropped-record fix, and the JavaScript group. Both failed the lock state machine and the tool-plan JSON, which came back as the inner arguments without the tool name. Thinking on additionally got the invoice exact (1,687 cents) and missed three tasks thinking-off passed, because the fenced code was indented and did not execute. Those three failures are output-format failures under a long reasoning trace, not a second algorithm result.

The 35B is worth using for this workload with thinking disabled: three extra passes and essentially the same successes per minute (**1,284** successful tasks per GPU-hour). It is not worth using with thinking left on. The earlier 10/16 versus 8/16 result was an easier suite and is not the comparison to use. The 2B rate is **1,211** successful tasks per GPU-hour.

## Hardware and software

| Item | Value |
|---|---|
| Node | scholar-k061, partition spark-batch, exclusive |
| GPU | NVIDIA GB10, compute capability 12.1 |
| Driver | 595.71.05, CUDA runtime 13.2 |
| Addressable memory reported by llama.cpp | 126,756 MiB, VMM off |
| Host RAM | 123 GiB, plus 95 GiB swap (unused) |
| CPUs | 20 (10 Cortex-X925 + 10 Cortex-A725) |
| Slurm | 20 CPUs, 120,500 MB, 4:00:00 QOS wall |
| vLLM | 0.28.0 in `vllm/vllm-openai:v0.28.0`, built with Apptainer on the node-local NVMe because scratch is mounted `nodev` |
| llama.cpp | 0.7.0-dev, commit `31288c9`, `GGML_CUDA_NO_VMM=ON`, architecture `121a-real`, CUDA 13.1 |

vLLM sees unified memory as device memory (`123.79 GiB` in its own log). Free memory, not total memory, is what the startup check uses. After a server exit, `VLLM::EngineCore` processes were sometimes left behind and had to be killed before the next launch.

## How throughput is counted

For the OpenAI chat client, aggregate tok/s is the sum of `completion_tokens` on requests that were started after warmup and finished successfully, divided by the wall time from the start of the window through the last counted completion. In-flight requests are not successes. llama-bench `avg_ts` on a pure `tg` row is single-sequence decode. llama-batched-bench `speed_tg` is aggregate decode across `pl` sequences of random tokens, not chat.

Client time-to-first-token is missing on the eager runs because those generations were reasoning tokens and the client was only watching `content`. The CUDA-graph runs report TTFT.

## Qwen3.6 NVFP4, vLLM, CUDA graphs

Checkpoint `nvidia/Qwen3.6-35B-A3B-NVFP4`, 21.82 GiB on disk, 20.4 GiB loaded, architecture `Qwen3_5MoeForConditionalGeneration`, quantization `modelopt_mixed`. Weights were copied to `/tmp/models/qwen36-nvfp4` and loaded with `--safetensors-load-strategy eager`. NFS mmap loads hung.

Launch flags that produced the table:

```bash
vllm serve /tmp/models/qwen36-nvfp4 \
  --served-model-name nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --host 127.0.0.1 --port 8000 --tensor-parallel-size 1 --trust-remote-code \
  --max-model-len 131072 --max-num-seqs 16 --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.26 --kv-cache-dtype fp8 \
  --attention-backend flashinfer --moe-backend marlin \
  --enable-chunked-prefill --enable-prefix-caching \
  --safetensors-load-strategy eager --reasoning-parser qwen3
```

The log confirmed Marlin as the NVFP4 MoE kernel, FlashInfer attention, CUDA graph mode `FULL_AND_PIECEWISE`, and capture sizes 1, 2, 4, 8, 16, 24, 32. KV cache: **1,073,270 tokens**, **8.19x** at 131,072.

| Profile | Clients | Completed | Failed | Aggregate tok/s | TTFT p50 |
|---|---:|---:|---:|---:|---:|
| A, ~1042 in / 512 out | 1 | 9 | 0 | 74.1 | 0.19 s |
| A | 4 | 24 | 0 | 185.7 | 0.61 s |
| A | 8 | 32 | 0 | 264.3 | 1.13 s |
| A | 12 | 36 | 0 | 282.7 | 1.43 s |
| B, ~8224 in / 1024 out | 1 | 4 | 0 | 67.9 | 1.27 s |
| B | 4 | 12 | 0 | 154.7 | 2.99 s |
| B | 8 | 16 | 0 | 214.9 | 2.77 s |
| B | 12 | 24 | 0 | 236.8 | 2.78 s |

Profile A gained about 7% from 8 to 12 clients. Profile B gained about 10%. GPU utilization was about 96% during the profile A run at 8 clients. Twelve clients is the throughput-optimal point tested; 16 was not run on this server. The KV budget says 8 full 128k sequences fit, so 12 clients only works because these prompts are 1k–8k, not 128k.

### Eager mode, same checkpoint

| Profile | Clients | Aggregate tok/s |
|---|---:|---:|
| A | 1 | 10.8 |
| A | 2 | 20.6 |
| A | 4 | 39.8 |
| A | 8 | 78.7 |
| A | 12 | 114.5 |
| B | 1 | 10.5 |
| B | 2 | 20.4 |
| B | 4 | 39.6 |
| B | 8 | 75.4 |
| B | 12 | 110.9 |

Per-stream speed stayed near 11 tok/s and GPU use stayed near 21% at 12 clients. Do not serve this checkpoint with `--enforce-eager` except to debug a graph hang.

### Filled long context

One request, CUDA graphs, max context 131072:

- Prompt tokens: **118,391**
- Output tokens: **140**
- Wall time: **39.6 s**
- A passphrase inserted after the filler (`ORCHID-19`) was present in the output.

That is one successful near-120k prompt, not a concurrency sweep at that length. Output tok/s on this request is prefill-dominated (140/39.6).

### Five checked questions

Thinking was on (the reasoning parser reports reasoning tokens). The token budget was 512, and several answers were still inside the reasoning trace when the budget ended. Substring checks:

| Task | Result |
|---|---|
| Sum of evens from 1 to 9 (`f(10)` = 20) | Passed. The trace shows 2+4+6+8=20. |
| 12*17 | Passed. The text contains 204. |
| Ways to climb 10 stairs (89) | Failed. The trace computed the Fibonacci recurrence and was cut off before stating f(10). |
| Emit a specific tool-call JSON | Failed. The model quoted the request and did not finish a clean call inside the budget. |
| How many lines `range(5)` prints | Passed. The answer 5 is at the start of the text. |

3 of 5. This is a smoke check, not a 20-task coding suite. It is enough to show the model can do small exact coding questions, and that thinking mode will spend a 512-token budget before the final line.

## Ornith 1.5 NVFP4

`ornith-ai/Ornith-1.5-35B-A3B-NVFP4`, 22 GB, same vLLM flags, MTP off. Load: 20.4 GiB in 74 s. KV cache **1,329,715 tokens**, **10.14x** at 131,072. That is more KV headroom than Qwen3.6 at the same 0.26 utilization.

| Profile | Clients | Completed | Failed | Aggregate tok/s | TTFT p50 |
|---|---:|---:|---:|---:|---:|
| A | 1 | 9 | 0 | 75.1 | 0.20 s |
| A | 4 | 24 | 0 | 185.3 | 0.62 s |
| A | 8 | 32 | 0 | 258.7 | 1.14 s |
| A | 12 | 36 | 0 | 265.2 | 1.48 s |
| B | 1 | 5 | 0 | 68.9 | 1.22 s |
| B | 4 | 12 | 0 | 155.1 |  |
| B | 8 | 16 | 0 | 216.0 |  |
| B | 12 | 24 | 0 | 229.6 |  |

Ornith matches Qwen3.6 at one client and is 6% slower at 12 clients on profile A (265 vs 283) and 3% slower on profile B (230 vs 237). No separate coding suite was run on Ornith. MTP was not enabled. Public Spark numbers that quote ~500 tok/s were not reproduced here.

## Qwen3.5-2B Q4_K_M, llama.cpp

Model file: `unsloth/Qwen3.5-2B-GGUF` revision `f6d5376be1edb4d416d56da11e5397a961aca8ae`, Q4_K_M. Binary: `build-no-vmm`, flash attention on, 999 GPU layers.

| Measurement | tok/s |
|---|---:|
| llama-bench prefill, 512 tokens | 8945 |
| llama-bench decode, 128 tokens, short context | 148.4 |
| llama-bench decode, 128 tokens, depth 120,000 | 77.6 |
| llama-bench prefill at that depth | 5103 |

Batched random-token aggregate decode, unified KV, context pool 131072:

| Prompt | Generated | Parallel | Aggregate decode tok/s |
|---:|---:|---:|---:|
| 1024 | 256 | 1 | 149 |
| 1024 | 256 | 4 | 427 |
| 1024 | 256 | 8 | 701 |
| 1024 | 256 | 12 | 812 |
| 1024 | 256 | 16 | 895 |
| 8192 | 256 | 1 | 141 |
| 8192 | 256 | 8 | 534 |
| 8192 | 256 | 12 | 554 |

16 x (8192+256) does not fit in 131072 and was skipped.

llama-server chat, `--reasoning off`, context 131072, 16 slots, unified KV:

| Profile | Clients | Aggregate tok/s | Failed |
|---|---:|---:|---:|
| A | 1 | 123 | 0 |
| A | 4 | 321 | 0 |
| A | 8 | 419 | 0 |
| A | 12 | 453 | 0 |
| A | 16 | 446 | 0 |
| B | 1 | 119 | 0 |
| B | 4 | 266 | 0 |
| B | 8 | 311 | 0 |
| B | 12 | 336 | 0 |
| B | 16 | 11 | 4 failed, outputs truncated |

Profile A peaks at 12 clients. Profile B at 16 overflows the KV pool.

The historical 102 tok/s figure for this model was a short prompt inside a 131072 context. The new short-context decode is 148 tok/s. Decode with the cache actually filled to ~120k is 77.6 tok/s.

## What failed

- Qwen3.6 UD-Q4_K_M GGUF: `CUDA error: unspecified launch failure` in `cudaEventSynchronize` while uploading weights. Load modes `none`, `mmap`, and `dio` all abort. Qwen3.5-2B loads with the same binary.
- vLLM `serve --help` in 0.28 does not list flags. `--help=all` does. A first server was started without the tuning flags because of that, and was killed.
- Safetensors mmap from scratch NFS hung after the prefetch, with the engine at ~3 GB RSS and no further disk IO. `--safetensors-load-strategy eager` from local NVMe loads in about 95 seconds.
- `--load-format fastsafetensors` is not a choice in vLLM 0.28.
- `--gpu-memory-utilization 0.45` and `0.32` were rejected when free unified memory was lower than that fraction of 123.79 GiB. Orphaned `EngineCore` processes were the usual cause. 0.26 fit.
- An MTP relaunch with `--enforce-eager` died on that memory check because the previous engine was still resident. With CUDA graphs, global Marlin plus `--spec-method mtp` also failed because the MTP head is unquantized. Triton on the draft head is what ran.
- Login-node Apptainer pull of the vLLM image died while creating the SIF on scratch (`nodev`). The successful image is `/tmp/vllm-apptainer/vllm-openai-0.28.0.sif` on the compute node (7.7 GB). It does not survive a different node.

## Models not run

Nemotron, LFM2.5 FP8, GPT-OSS-20B MXFP4, and Mellum2.1 BF16 were measured in vLLM 0.28.0. Mellum’s GGUF and MTP head were not run. KAT-Coder, Flint, Qwen3-Coder-Next, Qwen3.8-27B, and Qwen3.8-Flash-Next were not downloaded. SGLang was not installed. No Q2/Q3 requantization was run.

## MTP

`--spec-method mtp` with global `--moe-backend marlin` dies during init: `moe_backend='marlin' is not supported for unquantized MoE`. The MTP head needs Triton. This is the config that ran:

```bash
--moe-backend marlin \
--speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'
```

Profile A only, CUDA graphs, 60 second closed loop, zero failures:

| Draft tokens | Clients | Aggregate tok/s | TTFT p50 | Completed |
|---:|---:|---:|---:|---:|
| 1 | 1 | 97.0 | 0.21 s | 12 |
| 1 | 8 | 332.4 | 0.50 s | 40 |
| 3 | 1 | 119.1 | 0.22 s | 14 |
| 3 | 8 | 375.5 | 0.41 s | 48 |

MTP 1 acceptance was about 90% (mean acceptance length about 1.9). MTP 3 acceptance by draft position was about 0.93, 0.82, 0.71 at low concurrency, and about 0.93, 0.85, 0.76 during the 16-client sweep (mean acceptance length 3.54).

## Round 2 (27 October 2026)

Jobs `481212` (`scholar-k078`) and `481223` (`scholar-k077`). Same vLLM 0.28.0 image, local NVMe weights, eager safetensors load, CUDA graphs, Marlin target, Triton MTP draft, FlashInfer, FP8 KV, context 131072.

`--max-num-seqs 24` at utilization 0.26, and again at 0.40, failed with no KV blocks left after weights and per-sequence state. Utilization **0.32** with 16 sequences allocated **1,198,372** KV tokens (9.14 full 131072-token sequences). Utilization **0.45** with 24 sequences allocated **2,403,554** KV tokens (18.34 sequences). Engine `num_requests_running` matched the client count on every row below.

| Model | MTP | Input | Output | Clients | Aggregate tok/s | Per-request tok/s | TTFT p50 | Active sequences | Successful |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Qwen3.6 | 3 | ~1044 | 512 | 8 | 378.8 | 48.8 | 0.47 s | 8 | 48/48 |
| Qwen3.6 | 3 | ~1044 | 512 | 12 | 466.0 | 39.6 | 0.77 s | 12 | 60/60 |
| Qwen3.6 | 3 | ~1045 | 512 | 16 | 525.8 | 33.8 | 0.86 s | 16 | 64/64 |
| Qwen3.6 | 3 | ~1045 | 512 | 24 | 580.7 | 25.3 | 1.26 s | 24 | 72/72 |
| Qwen3.6 | 3 | ~8225 | 1024 | 4 | 213.8 | 56.9 | 1.49 s | 4 | 15/15 |
| Qwen3.6 | 3 | ~8225 | 1024 | 8 | 302.0 | 40.0 | 1.50 s | 8 | 23/23 |
| Qwen3.6 | 3 | ~8225 | 1024 | 12 | 367.5 | 32.4 | 2.73 s | 12 | 24/24 |
| Qwen3.6 | 3 | ~8226 | 1024 | 16 | 411.4 | 27.4 | 2.90 s | 16 | 32/32 |
| Qwen3.6 | 3 | ~8226 | 1024 | 24 | 374.8 | 16.2 | 17.0 s | 24 | 24/24 |
| Qwen3.6 | 3 | ~120200 | ~227 | 2 | 5.1 |  | 86 s | 2 | 2/2, both codes retrieved |
| Qwen3.6 | 3 | ~120200 | ~203 | 4 | 4.6 |  | 132 s | 4 | 4/4, all codes retrieved |
| Qwen3.6 | 0 | ~120200 | ~211 | 2 | 5.2 |  | 76 s | 2 | 2/2, both codes retrieved |
| Qwen3.6 | 0 | ~120200 | ~210 | 4 | 5.0 |  | 119 s | 4 | 4/4, all codes retrieved |
| Ornith MTP1 | 1 | ~1042 | 512 | 1 | 95.0 | 95.3 | 0.21 s | 1 | 12/12 |
| Ornith MTP1 | 1 | ~1044 | 512 | 8 | 321.3 | 40.8 | 0.53 s | 8 | 40/40 |
| Ornith MTP1 | 1 | ~1044 | 512 | 12 | 399.3 | 33.6 | 0.80 s | 12 | 48/48 |
| Ornith MTP1 | 1 | ~8223 | 1024 | 1 | 85.9 | 85.9 | 1.30 s | 1 | 6/6 |
| Ornith MTP1 | 1 | ~8225 | 1024 | 8 | 248.5 | 32.0 | 2.63 s | 8 | 16/16 |
| Ornith MTP1 | 1 | ~8225 | 1024 | 12 | 294.1 | 25.2 | 3.57 s | 12 | 24/24 |

The 8–16 client rows used utilization 0.32. The 24-client rows used 0.45. Long-context output tokens are whatever the model produced before stopping; `min_tokens` was not forced, so those rows are prefill-bound. Aggregate tok/s there is completion tokens divided by wall time and is not a decode rate.

Twelve coding tasks were executed or parsed, with a 3072-token budget, on the MTP 3 server. **9 passed**: even-sum, binary search, key=value parser, tick count, two-bug clamp/mean, JavaScript sum (Node), Go sum (`go run`), dict update, and retry index. The two tool-call tasks returned incomplete JSON. The list-transformation task failed before a usable completion. Python, Node, and Go were actually run; passes are not substring checks.

## Recommendation

Use **Qwen3.6-35B-A3B NVFP4, vLLM 0.28.0, CUDA graphs, Marlin on the target MoE, Triton on the MTP head, 3 draft tokens, FlashInfer, FP8 KV**, weights on node-local NVMe, `--safetensors-load-strategy eager`, `--max-model-len 131072`.

- Short prompts: 24 clients at utilization 0.45 produced the highest aggregate, **581 tok/s**. Thirty-two clients fell to 465 tok/s with only 14 sequences active.
- 8k prompts: stop at **16 clients** (**411 tok/s**). Twenty-four clients were slower and the first token took 17 seconds.
- Four filled ~118k contexts with 1,024 forced output tokens decode together under MTP 3 at utilization 0.55 and `--max-num-seqs 24` (3.33 million KV tokens). Per-request decode is 22.8 tok/s versus 13.6 tok/s with MTP off. Keep MTP 3 for long contexts as well as short ones. A 0.45 start can profile a phantom ~50 GiB reservation and leave only ~300k KV tokens; if the log shows that, restart once at 0.55 and read `GPU KV cache size` before benchmarking.
- Ornith with one draft token did not beat Qwen3.6 MTP 3.
- Do not use `--enforce-eager`.
- `--max-num-seqs 24` needs utilization 0.45 on this node. 0.40 left no KV blocks.

Profile A at 32 clients was measured and was slower (465 tok/s, 14 active). Profile B should not be pushed past 16. The open measurement is GPT-OSS at 96 and 128 short-prompt clients, and at 64 clients on 8k prompts. Those points were still climbing when the 128-sequence launch failed its memory snapshot.

Raise `--gpu-memory-utilization` only after confirming `free` memory on the node. Kill leftover `VLLM::EngineCore` processes first. A value of 0.26 was the highest that fit after those processes had been using the machine; a clean node can go higher and will report a larger KV budget.

## Reproduce

From a Scholar login node, with the scripts in `/scratch/scholar/billin19/gb10-inference-bench`:

```bash
sbatch --account=scholar /scratch/scholar/billin19/gb10-inference-bench/worker.sbatch
```

The image must be rebuilt on the allocated node's `/tmp` if the job lands on a different node. The Qwen and Ornith weight directories under `/tmp/models` are also node-local. Hugging Face copies remain in `/scratch/scholar/billin19/hf-cache`.

Raw rows are in `results.csv`, `results.jsonl`, and `raw/` on that scratch path. A mirror of the report and scripts is in the workspace `gb10-inference-bench/` directory.
