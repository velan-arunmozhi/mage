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

The [structural OCL pilot](examples/ocl-structural/README.md) is a runnable first
example: extract Python imports, represent them with BESSER, and evaluate an OCL
boundary rule against conforming and violating code fixtures.

## OpenCode on Scholar

Use the [Scholar GPU setup guide](docs/scholar-opencode.md) for the working
two-terminal workflow: allocate a GPU, reuse an existing llama.cpp build, create
an SSH tunnel, and select the model in OpenCode.

The guide includes first-time setup, cleanup, and troubleshooting for CUDA startup
errors, binary architecture mismatches, and model selection. It prompts for your
own account and allocated node rather than embedding personal login details.

## Benchmark runs

Interactive OpenCode use and benchmark grading have separate setup paths:

- [Scholar/OpenCode guide](docs/scholar-opencode.md): model on the GPU node,
  interactive OpenCode on the login node.
- [eval-host](scripts/eval-host): OpenCode and the Docker benchmark grader on an
  amd64 Linux host, connected to a model server. Run
  `bash scripts/eval-host --help` for options.
- [scholar-session](scripts/scholar-session): an alternative server helper that
  can build llama.cpp under scratch. Its defaults differ from the working
  interactive guide; it is not required for that workflow.

To check the benchmark connection, first start the model using steps 1–2 of the
Scholar guide. On an **amd64 Linux host** with Docker running, open a MAGE
checkout and run the following. Enter the current allocated GPU hostname and
your own Scholar account when prompted:

```bash
printf 'Scholar username: '
IFS= read -r SCHOLAR_USER
printf 'Allocated GPU hostname: '
IFS= read -r GPU_NODE

bash scripts/eval-host \
  --model-ssh "${SCHOLAR_USER}@${GPU_NODE}" \
  --jump "${SCHOLAR_USER}@scholar.rcac.purdue.edu" \
  --no-remote-start \
  --setup-only
```

`--no-remote-start` reuses the server already running on the GPU node, avoiding
another build or different server settings. The script installs uv/Harbor if
needed and checks that a Docker container can reach the model. In setup-only
mode it keeps the tunnel open; press Ctrl+C after the check. Rerun the command
without `--setup-only` to start grading. The default requests one SWE-bench Pro
task per condition: OpenCode alone, then OpenCode with `.agents/skills`.

The benchmark repositories are supplied inside Harbor's task environments;
the Scholar checkout only supplies the model-server helper if you use it.
The amd64 host's checkout supplies the skills. Copying skills does not itself
create repository-specific MAGE models. This script is a setup/smoke-test path;
pin dataset/task IDs and experiment settings before using it for research.

If you prefer the helper to start the server, omit `--no-remote-start` and set
`--remote-repo` to the absolute path of your MAGE checkout on Scholar. The helper
uses `$RCAC_SCRATCH/mage-bench` by default and may build llama.cpp there even if
you already have a build under `~/llama.cpp`.

## Optional: Codex CLI

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

source ~/.bashrc
```
