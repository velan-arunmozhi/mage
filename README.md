MAGE argues that agent capability alone does not determine engineering progress. As codebases grow, agents must recover increasingly large amounts of architecture, business rules, constraints, and project-specific knowledge from low-level repository artifacts.

A bootstrapped MAGE environment would attempt to externalize some of this knowledge into reusable engineering representations so that agents do not need to reconstruct it repeatedly.

Our initial goal is to test whether this can be done efficiently on an existing codebase and whether the resulting representations improve agent performance.

Codex: 

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

source ~/.bashrc
```

OpenCode:

Get OpenCode installed on the Spark nodes:

```bash
npm install -g opencode-ai
```

If the skills in Opencode do not match what currently in the .agents/skills directory, run:

```bash
opencode debug skill
```

Start interactive slurm jobs:

```bash
sinteractive -A scholar -p spark-interactive \
  --gres=gpu:1 --cpus-per-task=10 --time=0-2:00:00
```

One-time install/build for llama:

```bash
module load modtree/spark
module load conda cuda cmake

git clone https://github.com/ggml-org/llama.cpp.git
cmake -S llama.cpp -B llama.cpp/build -DGGML_CUDA=ON -DLLAMA_CURL=ON
cmake --build llama.cpp/build -j 10
```

Running a model:

```bash
module load modtree/spark
module load cuda
export HF_HOME="$RCAC_SCRATCH/hf-cache"
cd ~/llama.cpp
```

Running Qwen3 (known working):

```bash
build/bin/llama-cli \
  -hf Qwen/Qwen3-4B-GGUF:Q4_K_M \
  -ngl 999 -c 8192 -fa on
```

Notes:

- Store model downloads in `$RCAC_SCRATCH`.
- `spark-interactive` is capped at ~60 GB RAM. Use `spark-batch` with `salloc` for larger models.
- Both Q4 and Q6 downloaded but crashed during CUDA model loading, even in a 100 GB exclusive batch allocation.

Two machines:

- On the Spark GPU node, `bash scripts/scholar-session serve` builds `llama-server` under `$RCAC_SCRATCH/mage-bench`, downloads `Qwen/Qwen3-4B-GGUF:Q4_K_M`, and serves it on `127.0.0.1:8080`. The clone on Scholar exists so that command can be run there. Benchmark repositories are not checked out on Scholar.
- On an amd64 Linux host, `scripts/eval-host` SSHs to that command, forwards the port, and runs OpenCode plus the benchmark grader in Docker. Those images are linux/amd64, which is why the grader is not on the GB10.

```bash
bash scripts/eval-host \
  --model-ssh billin19@scholar-k003 \
  --jump billin19@scholar.rcac.purdue.edu \
  --remote-repo ~/dev/mage \
  --setup-only
```

Drop `--setup-only` after a container on the amd64 host can call the model. The default then grades one SWE-bench Pro task twice: OpenCode alone, then OpenCode with `.agents/skills`.
