# OpenCode, Harbor, and context audit

Date: 29 October 2026. Context limit stays **131072**. No new model, no vLLM upgrade, no 262144 run in this round. The 99,073 + 32,000 figure below is copied from our Harbor logs, not from a public bug report.

## A. Actual software stack

| Layer | What ran the 12-task Qwen evaluation |
|---|---|
| Model | `nvidia/Qwen3.6-35B-A3B-NVFP4`, vLLM 0.28.0, MTP 3, Marlin target, Triton draft, FlashInfer, FP8 KV, CUDA graphs on, `--max-model-len 131072` |
| Thinking | Off on every chat completion, including compaction, via `scripts/reasoning_proxy.py` (`chat_template_kwargs.enable_thinking: false`) and the server default |
| Harbor | 0.24.0, `scripts/harbor-run`, dataset `swebenchpro`, agent `opencode`, agent timeout override 7200 s |
| OpenCode | **1.19.5**, installed inside each task container by Harbor (`npm i -g opencode-ai` with no pin, because `harbor` did not pass a version). Log line: `version=1.19.5`. This is the V1 session implementation (`packages/opencode/src/session/overflow.ts` at tag `v1.19.5`), not the V2-only settings page |
| Provider in those runs | Custom `vllm` provider, npm `@ai-sdk/openai-compatible`, base URL `http://host.docker.internal:18082/v1`. The model entry was only `{"name": "..."}`. **No `limit.context` and no `limit.output`** |
| Official eval helper | `scripts/lib/mage_scholar.py` `render_opencode` does set `limit.context` and `limit.output`. The 12-task script did not call it |
| Sessions | One OpenCode session per Harbor trial. Tasks do not share a session. Harbor does not summarize. The verifier runs after the agent, including after `NonZeroAgentExitCodeError` when a patch exists |
| MAGE | Six Cursor skills under `.agents/skills/`. No `.mage/` store in this repo. Not passed into the Harbor container |

OpenCode 1.19.5 constants, from that tag:

- `OUTPUT_TOKEN_MAX = 32000`. `maxOutputTokens` is `min(model.limit.output, 32000)`, or **32000 when `limit.output` is missing or 0**.
- Proactive overflow is disabled when `model.limit.context === 0` or `compaction.auto === false`.
- Otherwise a step is overflow when its token total is at least `context - maxOutputTokens` (there is no separate input limit on this model).
- Compaction keeps a recent tail of about 25% of the usable window, clamped to 2,000–15,000 tokens (`preserve_recent_tokens` can override).
- Tool-output pruning runs only if `compaction.prune` is set. It was not set, so it did not run.
- After a provider overflow, compaction continues with the exact sentence found in the trajectory: “The previous request exceeded the provider's size limit…”

## B. Context handling

What happened on the two tasks that hit the limit:

1. OpenCode did not compact before the failing call. The largest step input just before the error was 98,202 (vuls `78b52d6`) and 98,891 (qutebrowser `01d1d14`). With no advertised context, `isOverflow` does not treat that as full.
2. The call asked for **32,000** output tokens. vLLM rejected it: 99,073 prompt tokens + 32,000 reserved output = 131,073, one token over 131,072. Both numbers are in `harbor-qwen-off-rest` `opencode.txt` and `opencode.log` for those two trials.
3. OpenCode classified the HTTP 400 as `ContextOverflowError`, started a compaction request (`agent=compaction` in the log), and injected a synthetic user turn with `metadata.compaction_continue: true`.
4. The agent continued. It was not a Harbor stop. vuls `78b52d6` then passed. qutebrowser `01d1d14` continued, ran 21 test commands, and the verifier failed (46 required tests passed, `RESULT: FAILED`).

So the admission error was handled. It was not left unhandled, and compaction did not loop. The summary text itself is not stored as a separate artifact beyond the continued session. This audit does not claim specific facts were dropped. The only observed loss mechanism in source, when compaction does run, is that older turns are replaced by the summary while a recent tail is kept.

Why the error happened: the model metadata did not tell OpenCode the window was 131,072, and the default generation budget was 32,000. A prompt of 99,073 tokens is legal inside 131,072. It becomes illegal only because the requested output is reserved as well.

`scripts/run-harbor-12.sh` now sets `limit.context` 131072 and `limit.output` 8192, and `compaction.auto: true`. 8192 is the output budget already declared for the `qwen36-35b` profile in `mage_scholar.py`. With that budget, 99,073 + 8,192 = 107,265, which vLLM would accept. Proactive compaction starts when the reported step total reaches 131,072 − 8,192 = 122,880. This script change has not been executed in a new Harbor trial.

## C. Twelve-task failure analysis

Source: `harbor-jobs/harbor-qwen-off` and `harbor-jobs/harbor-qwen-off-rest`. Max context is the largest `step_finish` input token count in `opencode.txt`. Compactions are `agent=compaction` lines in `opencode.log`. Tool errors are OpenCode `tool: invalid` events. Qwen had almost none.

| Task | Passed | Max context | Compactions | Tool errors | Main failure cause | Evidence |
|---|---:|---:|---:|---:|---|---|
| qutebrowser `2e96108` | 1 | 73,389 | 0 | 0 | passed | 88 tool calls, 23 edits, 8 test commands, `RESULT: PASSED` |
| flipt `b68b896` | 0 | 71,339 | 0 | 0 | verifier failed after tests | 73 tools, 16 edits, 9 test commands, `RESULT: FAILED`. Far below the window |
| qutebrowser `01d1d14` | 0 | 98,891 | 1 | 0 | patch did not satisfy the verifier after compaction recovered | Overflow 99,073+32,000, then `compaction_continue`, 21 test commands, 46 required tests passed, `RESULT: FAILED` |
| vuls `78b52d6` | 1 | 98,202 | 1 | 0 | passed after compaction | Same overflow arithmetic, one compaction, 6 test commands, `RESULT: PASSED`. Harbor still recorded `NonZeroAgentExitCodeError` because the process exited non-zero |
| flipt `e42da21` | 0 | 65,354 | 0 | 0 | no project test run; verifier failed | 67 tools, 13 edits, 0 pytest/npm/go test commands |
| nodebb `84e0657` | 0 | 76,138 | 0 | 0 | verifier failed after tests | 114 tools, 11 edits, 25 test commands |
| element-web `f3534b4` | 1 | 68,633 | 0 | 0 | passed | 79 tools, 20 edits, 12 test commands |
| navidrome `d8e7943` | 0 | 50,925 | 0 | 0 | verifier failed; little test execution | 49 tools, 19 edits, 1 test command |
| vuls `f0b3a8b` | 1 | 54,260 | 0 | 0 | passed | 88 tools, 14 edits, 7 test commands |
| vuls `6eff6a9` | 1 | 93,284 | 0 | 1 | passed | 110 tools, 15 edits, 17 test commands, one invalid tool |
| openlibrary `fdbc0d8` | 0 | 82,365 | 0 | 0 | verifier failed after tests | 85 tools, 13 edits, 15 test commands |
| ansible `b2a289d` | 0 | 49,599 | 0 | 0 | agent never edited or ran tests | 14 tools, 0 edits, 0 test commands, `RESULT: FAILED` |

Ten of the twelve tasks never approached a compaction. Their failures are verifier results after ordinary agent work, or, for ansible and the second flipt task, stopping without the project tests. They are not context-management failures on this evidence. The two tasks that did overflow both continued. One passed and one failed the tests.

## D. Configuration fixes

| Change | Before | After | Why | Validated? |
|---|---|---|---|---|
| OpenCode model limit in `scripts/run-harbor-12.sh` | No `limit` field. Output budget fell through to 32,000. Proactive overflow check saw no context | `limit.context` 131072, `limit.output` 8192, `compaction.auto` true | Stops the one-token admission failure and lets proactive compaction see the real window | Not re-run. The arithmetic is the same check vLLM already logged |
| Inference server, thinking-off proxy, Harbor version, OpenCode version | unchanged | unchanged | The serving baseline stays fixed | Existing 131072 serves and the 12-task run |

Tradeoff: an 8,192 output cap can truncate a very long single edit. The 12-task completion sizes were about 18,199 tokens per task across the whole session, not per call. Calls that truly need more than 8,192 tokens in one response would be cut. That is the same budget the repo’s `qwen36-35b` profile already declares.

## E. MAGE evaluation readiness

Not ready for a fair Harbor comparison.

Implemented today:

- Six Cursor skills: structural, behavioral, ownership, decision, measurement, provenance, plus `mage-orchestrate`. They instruct an agent that already has this repository open in Cursor.
- `render_opencode` can publish context and output limits. It does not install MAGE skills into the task container.
- The skills say persistent models live under `.mage/`. That directory has no model files here.

Not implemented for this benchmark:

- OpenCode does not see those skills. Harbor did not copy them into `~/.config/opencode/skills`.
- Nothing in the 12 trajectories calls a MAGE tool.
- There is no automatic sync from the repository under test into a MAGE store, and no measurement of lookups, constraint checks, or survival across compaction.
- A MAGE condition would add instructions and tools the baseline does not have. That overhead has not been measured.

MAGE information would survive OpenCode compaction only if it lives outside the chat transcript and the agent calls it again after compaction. That path is not wired. Building it, without putting benchmark solutions into the store, is the missing integration.

## F. Targeted benchmark results

No new Harbor trial was run in this round. The 12-task table above is the baseline at 128K with the old, unset model limits. A MAGE arm was not run.

The earlier 262144 reruns stay exploratory and are not the evaluation context. They removed the admission error and did not raise the pass count overall (qutebrowser `01d1d14` flipped 0 to 1; vuls `78b52d6` flipped 1 to 0).

## G. Research implications

1. The seven verifier failures are not explained by context overflow. Two tasks hit an admission error and both continued. Five passes and five failures happened with max step input between 50k and 93k and no compaction. Ansible never edited the tree.
2. OpenCode 1.19.5 did not compact proactively in these runs, because the model entry had no context limit. It did compact automatically after vLLM returned 400, which is the installed overflow-recovery path.
3. Recovery from that specific vLLM error worked once on each of the two tasks. The session continued and the verifier ran. There was no compaction retry loop in the logs.
4. The server side of 131072 is already the frozen platform. Reliable agent operation also needs the OpenCode limits now written into `run-harbor-12.sh`. That setting is not yet confirmed by a new trial.
5. There is no stored compaction summary to show that a specific constraint was lost. The qutebrowser `01d1d14` failure after compaction is a failed patch, not proof the summary dropped a fact.
6. MAGE cannot preserve or recover that information in these Harbor runs. It is not on the agent’s tool list.
7. The informative tasks for a later compaction study are the two that actually overflowed: qutebrowser `01d1d14` and vuls `78b52d6`. Tasks that finished under 80k tokens do not test the hypothesis.
8. Next experiment: rerun those two tasks, and at most two more high-context failures (`openlibrary`, `nodebb`), on the frozen Qwen server with the new 131072/8192 OpenCode limits. Record whether compaction now happens before the 400, and whether the verifier result changes. Do not add MAGE until an OpenCode skill can read a store built without the benchmark patch.

## Completion

The installed OpenCode and Harbor path is traced against tag `v1.19.5` and the trial logs. The 12 failures are classified from those logs. The output-budget mismatch is fixed in the runner script and not yet re-executed. MAGE is not ready for a controlled comparison.
