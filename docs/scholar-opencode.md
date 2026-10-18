# OpenCode on Scholar: quick setup

Use two terminals logged into Scholar. Run the model on a GPU node and OpenCode
on the login node. This assumes a checkout at `~/mage`, OpenCode installed on
the login node, and llama.cpp built at `~/llama.cpp` (see the [main README](../README.md)
for installation and build commands).

## 1. Terminal 1: start the model

Request a GPU, then run the existing server:

```bash
sinteractive -A scholar -p spark-interactive \
  --gres=gpu:1 --cpus-per-task=10 --time=0-2:00:00
```

Within this job:

```bash
hostname
module load modtree/spark
module load cuda

HF_HOME="$RCAC_SCRATCH/hf-cache" \
"$HOME/llama.cpp/build/bin/llama-server" \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl 999 -c 16384 -np 1 -fa on \
  --jinja --alias qwen3-4b --host 127.0.0.1 --port 8080
```

Copy the hostname. Wait for `model loaded` and `listening on http://127.0.0.1:8080`.
Leave this terminal open. No rebuild is needed if the server already exists.

## 2. Terminal 2: connect to the model

Stay on the Scholar login node. Replace `ALLOCATED_GPU_HOSTNAME` below with the
hostname from Terminal 1:

```bash
GPU_NODE=ALLOCATED_GPU_HOSTNAME
TUNNEL_SOCKET="$HOME/.mage-model-tunnel"
ssh -M -S "$TUNNEL_SOCKET" -fN -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18080:127.0.0.1:8080 "$GPU_NODE"
curl -fsS --max-time 10 http://127.0.0.1:18080/v1/models
```

A JSON response containing `qwen3-4b` means the connection works. Returning to
the prompt is expected; the tunnel runs in the background.

## 3. Terminal 2: launch OpenCode

In the same login shell:

```bash
cd ~/mage
export OPENCODE_CONFIG_CONTENT='{
  "provider": {
    "scholar": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Scholar GPU",
      "options": {"baseURL": "http://127.0.0.1:18080/v1", "apiKey": "local"},
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
If the skill is missing, run `opencode debug skill` from `~/mage`.

## 4. Stop

Exit OpenCode, then in Terminal 2:

```bash
ssh -S "$TUNNEL_SOCKET" -O exit "$GPU_NODE"
unset OPENCODE_CONFIG_CONTENT
```

In Terminal 1, press Ctrl+C, then `exit` to release the GPU allocation.

If OpenCode reports `Exec format error`, run it on the login node. If the
connection fails, check that the server and allocation are still running and
that the tunnel uses the current GPU hostname. Keep the server at 16K context
and one slot, matching the client configuration above.
