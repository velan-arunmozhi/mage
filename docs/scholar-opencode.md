# OpenCode with a Scholar GPU model

Run the model on an allocated Scholar Spark GPU node and OpenCode on a Scholar
login node. An SSH tunnel connects them. Use two terminals and keep the GPU
allocation open while working.

```text
Terminal 1: Scholar GPU node -> llama-server on 127.0.0.1:8080
Terminal 2: Scholar login node -> OpenCode -> tunnel on 127.0.0.1:18080
```

The working setup uses Qwen3-4B Q4_K_M, a 16,384-token context, and one server
slot. Model loading and an interactive OpenCode session succeeded with this
configuration. That establishes a usable connection, not benchmark quality or
reliable tool use on every task.

## Before starting

- Have Scholar access, Purdue authentication, and permission to use the
  `scholar` account and `spark-interactive` partition. Substitute your approved
  account/partition if your allocation differs.
- Have a MAGE checkout at `~/mage` on Scholar, including the skills you want to
  use. If it lives elsewhere, adjust the `cd` commands below. Both terminals
  use Scholar's shared home directory.
- Have OpenCode available on the login node. Run `opencode --version` there.
  If it is missing, follow the [OpenCode installation instructions](https://opencode.ai/docs/#install)
  on that machine. For a user-local installation:

  ```bash
  curl -fsSL https://opencode.ai/install | bash
  ```

  Reopen the login shell if needed so the installer-added PATH takes effect.
  The configuration below follows OpenCode's 1.x provider interface. Check
  compatibility before switching to a different major version.

- Have a CUDA-enabled `llama-server` at `~/llama.cpp/build/bin/llama-server`,
  built for the Spark node architecture. If it is missing, use the
  [one-time build instructions](#one-time-build-if-llama-server-is-missing)
  after obtaining a GPU allocation.

Commands below prompt for your account and allocated hostname. No personal
account or fixed compute node is embedded in the instructions. Run each block
in its labeled terminal; variables do not transfer between terminals.

## 1. Terminal 1: request a GPU

From your computer, log into Scholar with your own account:

```bash
printf 'Scholar username: '
IFS= read -r SCHOLAR_USER
ssh -l "$SCHOLAR_USER" scholar.rcac.purdue.edu
```

On the Scholar login node, request an interactive allocation:

```bash
sinteractive -A scholar -p spark-interactive \
  --gres=gpu:1 --cpus-per-task=10 --time=0-2:00:00
```

Wait until the allocation is granted and the shell is on the GPU node. Then:

```bash
hostname
module load modtree/spark
module load cuda
```

Copy the hostname printed by `hostname`; Terminal 2 needs this allocation's
actual node. A new allocation can have a different hostname.

Module reload/version messages are normal. If the prompt returns, continue.
Running an existing server build does not require loading Conda or CMake.
If the combined module load appears stuck, interrupt it and load just `cuda`,
then check that the server executable can start:

```bash
module load cuda
"$HOME/llama.cpp/build/bin/llama-server" --version
```

For heavier runs, Scholar also offers the `spark-batch` partition. Check the
[current RCAC Spark guidance](https://docs.rcac.purdue.edu/userguides/scholar/scholar-spark/)
for access and resource requests. Interactive nodes are shared; batch resources
can be requested exclusively. Do not assume the old approximate 60 GB figure is
a current allocation limit, or that a larger allocation will fix a CUDA error.

## 2. Terminal 1: start the model server

Run this on the allocated GPU node:

```bash
HF_HOME="$RCAC_SCRATCH/hf-cache" \
"$HOME/llama.cpp/build/bin/llama-server" \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl 999 -c 16384 -np 1 -fa on \
  --jinja --alias qwen3-4b \
  --host 127.0.0.1 --port 8080
```

This launches the existing executable without rebuilding it. Weights are cached
under scratch; the first model download can take longer. The foreground process
prints startup errors directly.

Wait for both messages:

```text
model loaded
listening on http://127.0.0.1:8080
```

Leave this process and terminal open. Keep `-np 1`: the successful session used
one slot. The 16K context leaves room for skill content and tool definitions;
it still has a finite limit, so begin with a fresh OpenCode chat.

Both endpoints in this guide bind to loopback. Access from the login node is
through your authenticated SSH tunnel. The `local` API key in the client config
below is a placeholder, not a Purdue credential or a secret.

## 3. Terminal 2: connect the login node to the GPU

Open a second terminal on your computer and log into Scholar:

```bash
printf 'Scholar username: '
IFS= read -r SCHOLAR_USER
ssh -l "$SCHOLAR_USER" scholar.rcac.purdue.edu
```

Stay on this login node. Do not request another GPU allocation here. OpenCode
will run in this shell, where its installed binary must match the machine.

Enter the hostname from Terminal 1 and create the tunnel:

```bash
printf 'Allocated GPU hostname from Terminal 1: '
IFS= read -r GPU_NODE
TUNNEL_SOCKET="$HOME/.mage-model-tunnel"

ssh -M -S "$TUNNEL_SOCKET" -fN \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18080:127.0.0.1:8080 \
  "$GPU_NODE"

curl -fsS --max-time 10 http://127.0.0.1:18080/v1/models
```

Authenticate if prompted. The response should contain model ID `qwen3-4b`;
the working server also reported `n_ctx: 16384` in its model metadata.

Returning to the prompt after the JSON response is expected. The tunnel runs
in the background. This check does not launch OpenCode.

Keep using this same login shell: the tunnel endpoint is local to this login
machine. A separate login session could land on a different login host.

## 4. Terminal 2: select the model and launch OpenCode

From the login shell used for the tunnel:

```bash
cd ~/mage

export OPENCODE_CONFIG_CONTENT='{
  "provider": {
    "scholar": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Scholar GPU",
      "options": {
        "baseURL": "http://127.0.0.1:18080/v1",
        "apiKey": "local"
      },
      "models": {
        "qwen3-4b": {
          "name": "Qwen3 4B on Scholar",
          "limit": {
            "context": 16384,
            "output": 4096
          }
        }
      }
    }
  },
  "model": "scholar/qwen3-4b"
}'

opencode --model scholar/qwen3-4b
```

Confirm that the selected model is **Qwen3 4B on Scholar**. An allocation alone
does not change OpenCode's provider. This inline configuration lasts in this
shell; it does not overwrite your saved OpenCode configuration.

Start a fresh chat and try:

> Load the measurement skill and explain it in three sentences. Do not run
> measurements or inspect supporting files.

If skill discovery looks wrong, exit OpenCode and run `opencode debug skill`
from `~/mage`. The checkout must contain `.agents/skills/measurement/SKILL.md`.

## 5. Finish the session

In Terminal 2, exit OpenCode and close the tunnel:

```bash
ssh -S "$TUNNEL_SOCKET" -O exit "$GPU_NODE"
unset OPENCODE_CONFIG_CONTENT
```

In Terminal 1, press **Ctrl+C** to stop the foreground model server. Run `exit`
to leave the interactive GPU allocation. The allocation also ends at its
requested time limit; repeat the allocation and tunnel steps next time.

## One-time build if llama-server is missing

Run these commands on an allocated Spark GPU node, after the module commands
in step 1. An existing executable needs no rebuild.

```bash
if [ ! -x "$HOME/llama.cpp/build/bin/llama-server" ]; then
  module load cmake
  if [ ! -d "$HOME/llama.cpp" ]; then
    git clone https://github.com/ggml-org/llama.cpp.git "$HOME/llama.cpp"
  fi
  cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" \
    -DGGML_CUDA=ON -DLLAMA_CURL=ON
  cmake --build "$HOME/llama.cpp/build" \
    -j "${SLURM_CPUS_PER_TASK:-10}" --target llama-server
fi
```

If the directory exists with only `llama-cli` built, this builds the server
target using that directory. Return to step 2 afterward. Keep the build on the
architecture it was built for; a shared home directory does not make binaries
portable between login nodes and ARM GPU nodes.

For reproducible experiments, record the versions actually used:

```bash
# Terminal 1, on the GPU node:
"$HOME/llama.cpp/build/bin/llama-server" --version
git -C "$HOME/llama.cpp" rev-parse HEAD

# Terminal 2, on the login node:
opencode --version
```

## Optional: test the model directly with llama-cli

This checks local inference without OpenCode or an SSH tunnel. Stop the model
server first so both processes do not compete for the allocated GPU memory.
On the allocated GPU node, after loading the modules from step 1:

```bash
cmake --build "$HOME/llama.cpp/build" \
  -j "${SLURM_CPUS_PER_TASK:-10}" --target llama-cli

HF_HOME="$RCAC_SCRATCH/hf-cache" \
"$HOME/llama.cpp/build/bin/llama-cli" \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl 999 -c 8192 -fa on
```

If CMake is not available, load it with `module load cmake` before building the
CLI target. Exit the CLI before restarting the server. The 8K context here is
for a direct model check; use the server and client settings above for OpenCode.

## Troubleshooting

| Symptom | Check or next action |
| --- | --- |
| CUDA illegal memory access during startup | The server crashed; waiting on its endpoint will not repair it. Keep the full error output. The working path uses one slot and 16K context. Retry with `-c 8192 -np 1` only as a startup diagnostic, and run `nvidia-smi` if it still fails. An earlier 32K/default-slot attempt failed; the exact cause was not established. |
| 8K starts but the skill does not fit | 8K is a diagnostic setting. Test 16K on the server before restoring the client context to 16,384. Keep client limits consistent with the actual server. |
| `opencode: Exec format error` | Run OpenCode on the login node where it works. Check `uname -m` and `file "$(command -v opencode)"` there if needed. A binary installed for another architecture cannot be reused just because its path is shared. |
| A prompt utility reports `Exec format error` | This is a shell-startup utility, separate from llama-server. If a shell prompt is available, continue; fix that utility's installation for the node architecture separately. |
| `llama-server` is missing or cannot execute | Use the one-time server build on the GPU node. A working `llama-cli` alone does not supply `llama-server`. |
| `curl` cannot reach port 18080 | Check that Terminal 1 still shows a running server, the allocation is alive, and the tunnel uses the current GPU hostname. Run OpenCode and the tunnel on the same login host. |
| Port 18080 is already in use | Check an existing guide-created tunnel with `ssh -S "$HOME/.mage-model-tunnel" -O check "$GPU_NODE"`. Close that tunnel before recreating it. If a different process owns the port, choose another local port and update both the tunnel and `baseURL`; do not stop unrelated processes. |
| OpenCode still shows a hosted model | Reapply the inline configuration in Terminal 2 and launch with `--model scholar/qwen3-4b`. |
| File reads fail with a missing `filePath` argument | That is a malformed tool call. The skill folder can still be valid and already loaded. Try a fresh chat and a short overview request; more GPU capacity does not fix incorrect tool arguments. |
| A helper starts building llama.cpp again | `scripts/scholar-session` defaults to a different source/cache directory. This guide directly runs `~/llama.cpp/build/bin/llama-server` to reuse the existing build. |

The interactive workflow does not require the Docker benchmark grader or
`scripts/eval-host`. Benchmark execution is a separate setup on a suitable host.
The project's uv environment is for Python tools such as measurement; it does
not select OpenCode's model provider or replace the GPU server.

## References

- [OpenCode installation](https://opencode.ai/docs/#install)
- [OpenCode llama.cpp provider](https://opencode.ai/docs/providers/#llamacpp)
- [OpenCode configuration](https://opencode.ai/docs/config/)
- [llama.cpp server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp tool calling](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
