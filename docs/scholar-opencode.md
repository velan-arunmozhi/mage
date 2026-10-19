# OpenCode on Scholar: quick setup

Use two terminals on a Spark GPU node. The model server and OpenCode both run
there when the OpenCode binary is ARM, which is the case for the install under
`~/.nvm` on `scholar-k003`. Login nodes such as `scholar-fe04` are x86_64.
Home is shared, so one `npm install -g opencode-ai` can run on only one of
those CPUs.

A checkout at `~/dev/mage` was used for the working session. Any clone is fine.
`cd` there before launching OpenCode.

If `nvidia-smi -L` already lists an NVIDIA GB10, skip the allocation below.
`scholar-k003` is that kind of node.

## 1. Terminal 1: start the model

Request a GPU only when this shell has none:

```bash
sinteractive -A scholar -p spark-interactive \
  --gres=gpu:1 --cpus-per-task=10 --time=0-2:00:00
hostname
```

Home is capped at 25 GB. Put the llama.cpp source on scratch and point
`~/llama.cpp` at it. A VS Code shell often has no `module` command; sourcing
the profile defines it. The system compilers on `scholar-k003` were enough to
finish a build when `module` was missing.

```bash
source /etc/profile.d/modules.sh
module load modtree/spark
module load conda cuda cmake
mkdir -p "$RCAC_SCRATCH/src"
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$RCAC_SCRATCH/src/llama.cpp"
ln -sfn "$RCAC_SCRATCH/src/llama.cpp" "$HOME/llama.cpp"
cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DGGML_CUDA=ON -DLLAMA_CURL=ON
cmake --build "$HOME/llama.cpp/build" -j 10
```

Skip the clone and build when `~/llama.cpp/build/bin/llama-server` already
exists. Start the server and leave this terminal open:

```bash
source /etc/profile.d/modules.sh
module load modtree/spark
module load cuda
HF_HOME="$RCAC_SCRATCH/hf-cache" \
"$HOME/llama.cpp/build/bin/llama-server" \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl 999 -c 16384 -np 1 -fa on \
  --jinja --alias qwen3-4b --host 127.0.0.1 --port 8080
```

Wait until it is listening on `http://127.0.0.1:8080`.

## 2. Terminal 2: launch OpenCode on the same node

`source ~/.nvm/nvm.sh` when `opencode` is not on `PATH`. Confirm the binary
matches this CPU before starting it:

```bash
uname -m
file "$(command -v opencode)"
```

On `scholar-k003` both should be `aarch64`. The server is local, so the client
uses port 8080:

```bash
cd ~/dev/mage
export OPENCODE_CONFIG_CONTENT='{
  "provider": {
    "scholar": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Scholar GPU",
      "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local"},
      "models": {
        "qwen3-4b": {
          "name": "Qwen3 4B on Scholar",
          "limit": {"context": 16384, "output": 4096}
        }
      }
    }
  },
  "model": "scholar/qwen3-4b"
}'
opencode --model scholar/qwen3-4b
```

Start a fresh chat: **"Load the measurement skill and explain it in three sentences."**
A loaded skill followed by a 404 for some other URL is still a success. The
404 means a web fetch missed. The skill text came from the checkout. If the
skill is missing entirely, run `opencode debug skill` from the repo root.

## 3. Login node, when the binary is x86_64

Use this only when `file "$(command -v opencode)"` on the login node reports
an x86-64 executable. `scholar-fe04` cannot run the aarch64 binary installed
from `scholar-k003`, and the reverse is also true. Reinstall on the node where
OpenCode should run:

```bash
source ~/.nvm/nvm.sh
npm install -g opencode-ai
```

From the login node, with `GPU_NODE` set to the hostname printed in Terminal 1:

```bash
GPU_NODE=scholar-k003
TUNNEL_SOCKET="$HOME/.mage-model-tunnel"
ssh -M -S "$TUNNEL_SOCKET" -fN -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18080:127.0.0.1:8080 "$GPU_NODE"
curl -fsS --max-time 10 http://127.0.0.1:18080/v1/models
```

JSON containing `qwen3-4b` means the tunnel is up. Launch OpenCode with the
same config as above, and set `baseURL` to `http://127.0.0.1:18080/v1`.

SSH from a compute node to `scholar.rcac.purdue.edu` asks for Microsoft
Authenticator. Duo Mobile codes are not accepted. An ed25519 key appended to
`~/.ssh/authorized_keys` satisfies that prompt:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
ssh -o PreferredAuthentications=publickey -o IdentitiesOnly=yes scholar.rcac.purdue.edu
```

## 4. Stop

Exit OpenCode. On the login-node path, close the tunnel:

```bash
ssh -S "$HOME/.mage-model-tunnel" -O exit "$GPU_NODE"
```

In Terminal 1, press Ctrl+C. If this shell is an `sinteractive` job, `exit`
releases the GPU.
