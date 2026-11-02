# GB10 inference benchmark

Measurements are taken on Purdue Scholar `spark-batch` nodes (NVIDIA GB10), not on the local workstation. The durable copy of logs and results is:

`/scratch/scholar/billin19/gb10-inference-bench/`

This directory is the authoring copy. Scripts are copied to scratch before `sbatch`.

## Allocation

```bash
sbatch --account=scholar /scratch/scholar/billin19/gb10-inference-bench/worker.sbatch
```

The worker runs, in order:

1. `scripts/00-probe.sh`
2. `scripts/02-llama-baseline.sh` (cached GGUF llama.cpp benches and a llama-server concurrency sweep)
3. `scripts/03-vllm-qwen36.sh` (NVFP4 vLLM, after the ARM64 image exists)
4. Any `queue/pending/*.sh` scripts dropped in later

QOS `normal` allows 4 hours and 2 jobs. The partition is exclusive when the job takes the full node (20 CPUs, 120500 MB, 1 GB10).

## Result files

- `experiments.jsonl` — every attempt
- `results.jsonl` and `results.csv` — successful measurements
- `raw/` — engine stdout and per-request JSON
- `logs/` — server and Slurm logs
- `progress.md`, `leaderboard.md`, `failures.md`

Aggregate tokens/sec for the OpenAI client counts completion tokens of successful requests launched after warmup, divided by the wall time from the window start through the last counted completion. Incomplete requests are not successes. llama-bench `avg_ts` is a single-sequence pp or tg rate. llama-batched-bench `speed_tg` is aggregate decode tokens/sec across `pl` sequences of random tokens.

## Resume

If the allocation ends, read `progress.md`, `pending.json`, and `logs/worker.log` on scratch, then submit `worker.sbatch` again. Completed raw files are left in place; do not delete them.
