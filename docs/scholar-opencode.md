# Scholar model serving and Harbor grading

Scholar's Spark nodes serve the model. An AMD64 host grades with OpenCode and Harbor inside `linux/amd64` containers. The AMD64 host reaches the server through an SSH local forward to `127.0.0.1` on the GPU node. That address is node-local. Record the node's real hostname; do not treat `127.0.0.1` as a cluster-wide endpoint.

`scripts/lib/mage_scholar.py` is the config contract. `scripts/scholar-session` and `scripts/eval-host` both call it, so the CLI, the `llama-server` argv, the OpenCode context and output limits, and the Harbor job name come from one resolved config. Precedence is explicit CLI, then environment, then the chosen profile, then the legacy default.

The legacy default, used when no profile is selected, is `Qwen/Qwen3-4B-GGUF:Q4_K_M`, alias `qwen3-4b`, context 8192, `-ngl 999`, `-fa on`, port 8080, bind `127.0.0.1`. The recommended evaluation pilot is the `qwen36-35b` profile. Those are different configs.

## What survives a job

Home and scratch directories persist across allocations. The SLURM job, the `llama-server` process, and the shell environment do not. A later shell must load modules or apply the CUDA fallback again, and it must start the server again.

If `HOME` is unset, the scripts recover it from `getent passwd`. `RCAC_SCRATCH` is used only when an existing directory is found at `/scratch/scholar/$USER` or `/scratch/$USER`. The scripts do not create a guessed scratch root. `HF_HOME` defaults to `$RCAC_SCRATCH/hf-cache` when that scratch directory exists. `--scratch` / `MAGE_SCRATCH` is the bench root and may be created. `eval-host --remote-scratch PATH` forwards that path to the remote serve and to a managed batch script.

## Allocations

Pick the mode explicitly. Reachability of a hostname does not choose it.

| Mode | When | Command shape |
|---|---|---|
| Manual | You already hold `spark-interactive` or `spark-batch` | `--model-ssh USER@GPU_NODE --no-remote-start` |
| Managed batch | This command should submit the job | `--account`, `--partition`, `--gpus`, `--cpus`, `--mem`, `--time` |

`spark-interactive` is the short interactive partition and is capped at about 60 GB of RAM. `sinteractive` requests it and gives you a shell on the node. `spark-batch` is the larger partition. `salloc` reserves it and leaves you a shell; `sbatch` runs a script. The managed path uses `sbatch` and keeps the allocation alive by running `scholar-session serve --foreground` inside the job. `--help`, `status`, `plan`, and `--dry-run` do not request a GPU, submit a job, or download weights.

A verified working request for one Scholar account is:

```bash
salloc -A scholar -p spark-batch --gres=gpu:1 --cpus-per-task=20 --mem=100G --time=02:00:00
```

That request is one account's verified shape, not a quota that every account can use. Account, partition, and QOS must match `^[A-Za-z0-9_-]+$`. Memory must look like `100G`. Time may be minutes, `hh:mm[:ss]`, or `d-hh:mm:ss`. GPUs are 1–8 and CPUs are 1–128. A walltime of two hours or less prints a warning: a full SWE-bench Pro run may not finish, and a later run with the same Harbor fingerprint can resume.

From an AMD64 machine, `sbatch` is not local. Pass `--jump USER@scholar.rcac.purdue.edu`. A Scholar login node that already has `sbatch` can omit `--jump`. The scripts do not SSH to an arbitrary compute host and assume it can submit jobs.

After the job starts, the batch script writes `hostname` and `SLURM_JOB_ID` into the run directory, then `allocation.json`. `status` and `stop` treat a process as live only when the pid file's start time, command line, hostname, and SLURM job id still match. A recycled pid from an earlier allocation is left alone. Cancel runs only when `squeue` reports the job name this command submitted.

## CUDA on a module-less batch shell

Some Spark batch shells have no `module` command and no `/etc/profile.d/modules.sh`. `HOME`, `RCAC_SCRATCH`, and `TERM` can be unset, and the first `nvcc` on the node can be CUDA 12.0. When the required libraries are already resolvable, the script keeps that environment. Otherwise it tries `module load modtree/spark` and the conda CUDA/cmake modules. If `libcudart.so.13` is still missing and this directory exists, it uses the verified Scholar CUDA 13.1 tree:

```bash
export CUDA_ROOT=/apps/spack/scholar-dgx/apps/cuda/13.1.1-none-none-hfb3k4d
export PATH="$CUDA_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_ROOT/targets/sbsa-linux/lib:$CUDA_ROOT/lib64:${LD_LIBRARY_PATH:-}"
```

The server needs `libcudart.so.13`, `libcublas.so.13`, and `libcublasLt.so.13`. The runs that loaded the 14B and Qwen3.6 models used this library path. Those runs did not establish that `modtree/spark` was loaded. Set `MAGE_CUDA_ROOT` to point at a different tree. The log records which root was used and states when the fallback did not load `modtree/spark`.

## Managed memory

`GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` turns on CUDA managed memory in the ggml CUDA backend. On a GPU whose name contains `GB10`, `--cuda-managed auto` sets it. On other GPUs it leaves the variable unset. `on` and `off` override that. `off` unsets it. If the variable is already set, `auto` keeps the existing value.

This is a workaround. It is not a patched NVIDIA driver. A kernel-driver issue near 4 GiB boundaries was a hypothesis; the logs did not prove NVIDIA bug 1269, and they did not establish a precise 4 GiB threshold. `nvidia-smi` reporting about 302 MiB does not measure CUDA-managed unified memory. Use cgroup `memory.current` when you need an allocation-level figure.

## llama.cpp

A new clone is pinned to commit `31288c9` (0.7.0-dev, ARM64, CUDA 13.1, architecture `121a-real`). The cluster driver observed with that build was `595.71.05`, with 64 KiB pages. An existing checkout is reused and is not reset. `--allow-llama-update` builds a separate tree at `<src>-<commit>`.

The CMake line is `-DGGML_CUDA=ON` only. `-DLLAMA_CURL=ON` is omitted: current llama.cpp ignores it, and HTTPS downloads use OpenSSL. Before launch, the script checks `llama-server --help` for alias, jinja, port, and flash-attention flags. It does not add KV-cache quantization, CUDA graphs, or `-fa on` unless you pass them. The known-working Qwen3.6 profile uses `-fa off`. Extra server flags belong on `--llama-arg` and are recorded in the fingerprint.

`--llama-commit SHA` on `eval-host` records that commit in the Harbor fingerprint and forwards it to the remote `serve`. A new remote clone still pins `31288c9` when no commit is requested.

## Profiles

Profiles are known starting points. Selecting one does not mean every context or sampling setup works.

| Profile | Hugging Face ref / alias | Context and server flags | Standing |
|---|---|---|---|
| `smoke-4b` | `Qwen/Qwen3-4B-GGUF:Q4_K_M` / `qwen3-4b` | 16384 | Infrastructure smoke. A 40K context failed before the managed-memory workaround. |
| `coder-14b` | `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M` / `qwen2.5-coder-14b` | 4096, `-ngl 32`, `-fa off` | Load plus a two-token completion. A longer completion is not confirmed. |
| `qwen36-35b` | `unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M` / `qwen36-35b` | 131072, `-ngl 999`, `-fa off`, `-np 1` | Preferred pilot. Short prompt, coherent final answer, 128K capacity initialized. |
| `qwen30b-diagnostic` | `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q4_K_M` / `qwen3-coder-30b` | 4096 | Diagnostic only. `eval-host` refuses it unless `--allow-not-ready` is set. |
| *(no profile)* | Qwen3-4B Q4 / `qwen3-4b` | 8192, `-ngl 999`, `-fa on` | Legacy script default. Distinct from `smoke-4b`. |

Changing a profile's model without an explicit `--model-alias` is an error. Output limit must be smaller than context. There is no silent clamp from 128K to 8K or from Qwen3.6 to 4B.

### Previously observed server commands

These commands were run on `scholar-k060` with the ARM64 CUDA 13.1 build of commit `31288c9`, after the CUDA 13.1 library path above was on `LD_LIBRARY_PATH`. This repository update did not re-run them.

Qwen2.5-Coder-14B loaded in about 50 seconds and produced two tokens at a reported 6.86 tok/s. That is a load check, not a sustained benchmark:

```bash
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
export HF_HOME="$RCAC_SCRATCH/hf-cache"
"$HOME/llama.cpp/build/bin/llama-server" \
  -hf Qwen/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M \
  -ngl 32 -c 4096 -np 1 -fa off \
  --jinja \
  --alias qwen2.5-coder-14b \
  --host 127.0.0.1 --port 8080
```

Qwen3.6-35B-A3B at context 131072 completed one short-prompt answer (`finish_reason=stop`, 2377 generated tokens, about 50 generated tok/s, about 65 prompt tok/s on that short prompt). The same model at context 8192 with a 512-token cap returned coherent `reasoning_content` and empty `content` because the cap was exhausted. The 131072 result shows that the server initialized that capacity. It does not show long-prompt, tool-call, or SWE-bench Pro behavior. The log mentioned `mmproj-BF16.gguf` and that reasoning preservation is the default. Text benchmarks keep that default and do not add the vision projector.

```bash
export GGML_CUDA_ENABLE_UNIFIED_MEMORY=1
export HF_HOME="$RCAC_SCRATCH/hf-cache"
"$HOME/llama.cpp/build/bin/llama-server" \
  -hf unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M \
  -ngl 999 -c 131072 -np 1 -fa off --jinja \
  --alias qwen36-35b --host 127.0.0.1 --port 18080
```

The same launch through the script, on a GPU node:

```bash
MAGE_MODEL_HF='unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M' \
MAGE_MODEL_ALIAS=qwen36-35b \
MAGE_CONTEXT=131072 \
MAGE_FLASH_ATTN=off \
MAGE_GPU_LAYERS=999 \
  bash scripts/scholar-session serve
```

`qwen30b-diagnostic` loaded and reported high tok/s, then repeated `G`, `3`, or `/`. Load, HTTP 200, `/health`, and a large `n_ctx` are not a passing model.

## Health is separate from a correct answer

Before Harbor, the AMD64 host checks three things:

1. `/v1/models` contains the resolved alias.
2. `/slots` or `/props` reports `n_ctx` equal to the requested context. `n_ctx_train` is ignored.
3. A chat smoke returns valid JSON, nonempty final `content`, and `finish_reason=stop`, and the text is not a few characters repeated. `reasoning_content` is stored separately. Empty content with `finish_reason=length` is a budget failure, which is what the 512-token Qwen3.6 call did.

The tool smoke asks for an echo tool whose text contains `hello`, checks that the tool name and argument are the expected shape, writes the echo result from this script, and judges the follow-up as another chat. Model output and tool arguments are not executed. A smoke failure stops the run unless `--allow-smoke-failure` is set.

## Research conditions

Harbor runs one condition at a time, concurrency 1, with the same model, context, output budget, and task list.

| Condition | What runs |
|---|---|
| `baseline` | OpenCode alone |
| `mage` | OpenCode plus the six skills under `.agents/skills` (`structural`, `behavioral`, `ownership`, `decision`, `measurement`, `provenance`), passed as `--skill` |
| `both` | Those two jobs, separately, on the same resolved config |

`mage` copies skills only. A skills-plus-repository-representations condition is not implemented, and it is not a `--condition` value. One smoke task is not an aggregate SWE-bench Pro score.

The Harbor job name is `mage-<dataset>-<condition>-n<count>-<alias>-c<context>-<fingerprint>`. The fingerprint covers the model ref, revision, alias, context, sampling, reasoning, output limit, llama.cpp commit, dataset identity, task selection, condition, and runtime flags. The same config resumes. A different config gets a different job name.

## Dataset identity

The default Harbor alias remains `swebenchpro`. Harbor's main SWE-bench Pro adapter calls `load_dataset("ScaleAI/SWE-bench_Pro")["test"]` with no config, and its README still describes 731 tasks and `jefzda/sweap-images` (V1). On the Hugging Face Hub, the default config since 2026-09-22 is V2 (642 tasks, version 2.0.0). Config `v1` / tag `v1.0` is the 731-task set. Config `hard` is HARD-51. A registry token such as `swebenchpro@1.0` is not the paper release.

`swebench_release` stays `unverified` until a live run records what that Harbor binary actually loaded. V1, V2, and HARD-51 results stay in separate comparisons.

## Context is an experiment

| Context | Role |
|---|---|
| 8K–16K | Smoke and infrastructure |
| 32K | Pilot |
| 64K | Proposed compromise for longer agent traces |
| 128K | Comparison. Qwen3.6 initialized this capacity on a short prompt. |
| 256K | Stretch, only after the shorter settings are measured |

Record actual input tokens, output tokens, prefill and decode rates, time to first token, wall time, and cgroup memory. The Qwen3.6 rates above are one short-prompt observation.

## Commands

Inspect the resolved config. This does not allocate, download, or submit:

```bash
bash scripts/eval-host --dry-run \
  --model-profile qwen36-35b --context 131072 \
  --partition spark-batch --account scholar \
  --gpus 1 --cpus 20 --mem 100G --time 02:00:00 \
  --condition both --dataset swebenchpro --n-tasks 1
```

Managed batch from an AMD64 host:

```bash
bash scripts/eval-host \
  --model-profile qwen36-35b --context 131072 \
  --jump USER@scholar.rcac.purdue.edu \
  --partition spark-batch --account scholar \
  --gpus 1 --cpus 20 --mem 100G --time 02:00:00 \
  --condition both --dataset swebenchpro --n-tasks 1
```

Manual allocation, when `USER@GPU_NODE` is already inside a job and the server is up:

```bash
bash scripts/eval-host \
  --model-ssh USER@GPU_NODE --no-remote-start \
  --model-profile qwen36-35b --context 131072 \
  --condition both --n-tasks 1
```

Omit `--no-remote-start` to have the AMD64 host upload this tree's `scripts/scholar-session` and `scripts/lib`, then start the server. `--use-remote-checkout` runs `REMOTE_REPO/scripts/scholar-session` instead. The resolved config is passed as base64. The remote shell is `bash --noprofile --norc`, and the model string is not interpolated into the shell command. The default local tunnel port is 18080. `--remote-port` is an alias of `--port`; if both are set and they differ, the command exits.

`eval-host status` with no recorded run prints a message and does not SSH. `eval-host stop` cancels only the owned job id and name. `--keep-allocation` leaves that job running. A startup timeout defaults to 1800 seconds and then cancels the owned job.

OpenCode receives `OPENCODE_CONFIG_CONTENT` built from the resolved alias, context, and output limit, plus `OPENAI_BASE_URL` and `OPENAI_API_KEY=local`. Harbor's model id is `scholar/<alias>`.

## Run artifacts

Each run directory holds `allocation.json`, `model.json`, `environment.txt`, `server.log`, health JSON, smoke responses, tool-smoke JSON, tunnel diagnostics, Harbor logs, and a summary. The files omit secrets, keys, cookies, and raw untrusted prompts. Local state defaults to `$XDG_STATE_HOME/mage-eval` or `~/.local/state/mage-eval`. Remote run directories are `$HOME/mage-eval-jobs/<run-id>`.

## Troubleshooting

**CUDA crash or missing `libcudart.so.13`.** Read `environment.txt` and `server.log`. Confirm whether the fallback CUDA root was applied. A module-less shell will not have `modtree/spark` unless that module command succeeded. Rebuild against CUDA 13.1 before retrying a 12.0 `nvcc`.

**Repeated characters.** The server can be healthy and still emit `G`, `3`, or `/`. That is the `qwen30b-diagnostic` failure. Stop before Harbor. A high tok/s number does not reverse the smoke verdict.

**`module: command not found`.** Expected on some batch shells. The CUDA fallback above is the path that made the verified loads work. Install or source modules only if you intend to use them; the fallback does not claim it loaded them.

**Empty final answer with `finish_reason=length`.** The output budget was spent in `reasoning_content`. Raise the smoke or Harbor output limit. It must stay below the context. The script will not clamp it.

**Port already serves a different model.** If the pid file identifies this run's server, the script restarts it. If the process is unowned, the script exits and leaves it running.

**Two-hour job ended early.** Resume with the same model, context, dataset identity, tasks, and condition. The Harbor job name matches only that fingerprint.

## What this repository change checked

The coding session that added this pipeline ran `scripts/tests/test_mage_scholar.py` and `scripts/tests/test_scholar_pipeline.sh`. Those cover config precedence, profile argv, fingerprint changes, smoke verdicts, dataset-probe wording, batch-script injection checks, module-less CUDA fallback, GB10 managed-memory selection, stale and foreign pid refusal, owned-job cancel, SSH quoting, and dry-run/status paths that must not call SSH or `sbatch`. `bash -n` is part of the shell suite. `shellcheck` was not installed in that environment.

That session did not submit a SLURM job, download a model, open a Scholar GPU allocation, or run Harbor. The 14B and Qwen3.6 results above are earlier observations. A live Scholar run still has to confirm the current binary, the dataset release Harbor actually loads, long-prompt behavior, and tool-call behavior under OpenCode.
