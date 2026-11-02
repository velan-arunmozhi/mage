#!/usr/bin/env python3
"""Append benchmark records and keep results.csv in sync."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("BENCH_ROOT", "/scratch/scholar/billin19/gb10-inference-bench"))
EXPERIMENTS = ROOT / "experiments.jsonl"
RESULTS_JSONL = ROOT / "results.jsonl"
RESULTS_CSV = ROOT / "results.csv"

CSV_FIELDS = [
    "experiment_id",
    "timestamp",
    "status",
    "model",
    "hf_id",
    "revision",
    "quantization",
    "engine",
    "engine_version",
    "profile",
    "context_configured",
    "input_tokens",
    "output_tokens_requested",
    "output_tokens_actual",
    "concurrency_requested",
    "engine_running_max",
    "mode",
    "mtp",
    "draft_tokens",
    "kv_cache",
    "attention",
    "moe_backend",
    "aggregate_tok_s",
    "decode_tok_s",
    "prefill_tok_s",
    "e2e_per_request_mean",
    "e2e_per_request_median",
    "p95_latency_s",
    "ttft_p50_s",
    "ttft_p95_s",
    "completed",
    "failed",
    "duration_s",
    "peak_gpu_mem_mib",
    "notes",
]


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def record(obj: dict, summary: bool = True) -> None:
    append_jsonl(EXPERIMENTS, obj)
    if summary and obj.get("status") == "ok":
        append_jsonl(RESULTS_JSONL, obj)
        write_csv_row(obj)


def write_csv_row(obj: dict) -> None:
    new = not RESULTS_CSV.exists()
    with RESULTS_CSV.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new:
            writer.writeheader()
        row = {key: obj.get(key, "") for key in CSV_FIELDS}
        writer.writerow(row)
        fh.flush()
        os.fsync(fh.fileno())
