MAGE argues that agent capability alone does not determine engineering progress. As codebases grow, agents must recover increasingly large amounts of architecture, business rules, constraints, and project-specific knowledge from low-level repository artifacts.

A bootstrapped MAGE environment would attempt to externalize some of this knowledge into reusable engineering representations so that agents do not need to reconstruct it repeatedly.

Our initial goal is to test whether this can be done efficiently on an existing codebase and whether the resulting representations improve agent performance.

## Python environment

The project uses uv to manage a shared `.venv` and locked dependencies. From the
repository root:

```bash
uv sync
uv run python .agents/skills/measurement/scripts/measure.py .agents/skills/measurement/examples/four-chains.json
uv run python -m unittest discover -s .agents/skills/measurement/tests -v
```

`uv run` selects the project environment automatically. For an interactive shell,
run `source .venv/bin/activate`; select `.venv/bin/python` as the interpreter in
your editor. An absolute interpreter such as `/opt/homebrew/bin/python3` bypasses
the virtual environment even after activation.

The structural OCL pilot retains its separate environment because of the upstream
dependency conflict documented in its instructions.

For the working two-terminal OpenCode setup, follow the
[short Scholar setup guide](docs/scholar-opencode.md). The instructions below
also cover direct model use and benchmark setup.

The [structural OCL pilot](examples/ocl-structural/README.md) is a runnable first
example: extract Python imports, represent them with BESSER, and evaluate an OCL
boundary rule against conforming and violating code fixtures.

The [structural Alloy pilot](examples/alloy-structural/README.md) asks the same
boundary question, on the same model and fixtures, through the Alloy Analyzer
instead — and adds a transitive-closure check the matrix-lookup and OCL
approaches cannot express without separate graph code.

Codex: 

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

source ~/.bashrc
```

Scholar serves the model. An AMD64 host grades it. The full procedure, profiles, CUDA fallback, and allocation modes are in [docs/scholar-opencode.md](docs/scholar-opencode.md).

`scripts/scholar-session` on the GPU node and `scripts/eval-host` on the AMD64 host share one config. CLI overrides environment, then the selected profile, then the legacy default (`Qwen3-4B` Q4, context 8192, `-fa on`). The recommended pilot is `qwen36-35b` at context 131072 with `-fa off`. Qwen3-4B remains available as `smoke-4b` or as that legacy default. Earlier CUDA load crashes on larger GGUFs happened before `GGML_CUDA_ENABLE_UNIFIED_MEMORY=1` on GB10. That setting is a managed-memory workaround, not a driver patch. `qwen30b-diagnostic` can load and still emit repeated characters, so `eval-host` refuses it unless `--allow-not-ready` is set.

Store weights under scratch (`HF_HOME=$RCAC_SCRATCH/hf-cache`). `spark-interactive` is about 60 GB of RAM. Larger models use `spark-batch`. A new llama.cpp clone is pinned to commit `31288c9` and configured with `-DGGML_CUDA=ON` only.

Preview a run without a GPU, SSH, or download:

```bash
bash scripts/eval-host --dry-run \
  --model-profile qwen36-35b --context 131072 \
  --partition spark-batch --account scholar \
  --gpus 1 --cpus 20 --mem 100G --time 02:00:00
```

Managed batch from AMD64, which has no local `sbatch`:

```bash
bash scripts/eval-host \
  --model-profile qwen36-35b --context 131072 \
  --jump USER@scholar.rcac.purdue.edu \
  --partition spark-batch --account scholar \
  --gpus 1 --cpus 20 --mem 100G --time 02:00:00 \
  --condition both --dataset swebenchpro --n-tasks 1
```

An existing allocation:

```bash
bash scripts/eval-host \
  --model-ssh USER@GPU_NODE --no-remote-start \
  --model-profile qwen36-35b --context 131072 \
  --condition both --n-tasks 1
```

`--condition both` runs OpenCode alone, then OpenCode with `.agents/skills`, on the same model and task list. A skills-plus-representations condition is not implemented. One task is a smoke grade, not an aggregate SWE-bench Pro score. The same Harbor fingerprint resumes; a changed model or context does not.
