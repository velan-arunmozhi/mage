# Progress

Round 10 is an OpenCode and Harbor context audit, not a new model run. The write-up is `OPENCODE_HARBOR_CONTEXT_AUDIT.md`.

The 12-task Qwen logs show two real overflows, both `99073` prompt tokens plus a `32000` output reservation. OpenCode 1.19.5 compacted after the 400 and continued. Ten tasks never compacted. `run-harbor-12.sh` now advertises context 131072 and output 8192. That setting has not been re-executed. MAGE is not wired into the Harbor container.

Round 9, for reference: jobs `482102` and `482103`.

## GPT-OSS tool names

A doubled Harmony header, `to=functions.read<|channel|>commentary<|channel|>commentary`, is what vLLM 0.28 parses as the tool name `read<|channel|>commentary`. A single header parses as `read`. The 0.28 renderer already emits the legacy header order, so the vLLM 0.31 header rewrite does not apply. The patch cuts the recipient at `<|channel|>`. On the three-task rerun, qutebrowser `2e96108` had 0 channel markers in tool names and still scored 0. Vuls `78b52d6` scored 0 after the model wrote a raw header as text. Element-web did not start (Docker credentials). A full 12-task rerun is not justified.

## Qwen 262144

The old failures were 99,073 prompt tokens plus a requested 32,000 output tokens. The retry server has a 300,135-token KV pool, 1.14 times one 262,144 context. qutebrowser `01d1d14` passed, with no context error. Vuls `78b52d6` had no context error and scored 0. The largest step input was 105,787.

## Best use, on measurements that exist

- Short prompts: GPT-OSS, 96 clients, 1,184 tok/s.
- Eight-k prompts: GPT-OSS, 96 clients, 817 tok/s, after one 8k wave.
- Harbor tasks per GPU-hour: Qwen3.6 thinking off, 2.60 on the 12-task suite.
