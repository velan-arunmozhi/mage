#!/usr/bin/env python3
"""Ingest llama-bench JSONL and llama-batched-bench JSONL into the result logs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import record


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest_bench(path: Path, model: str, hf_id: str, quant: str, engine_version: str) -> int:
    count = 0
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "avg_ts" not in obj:
            continue
        n_prompt = int(obj.get("n_prompt") or 0)
        n_gen = int(obj.get("n_gen") or 0)
        n_depth = int(obj.get("n_depth") or 0)
        if n_gen == 0 and n_prompt > 0:
            profile = f"pp{n_prompt}"
            prefill = float(obj["avg_ts"])
            decode = None
            agg = prefill
        elif n_prompt == 0 and n_gen > 0:
            profile = f"tg{n_gen}"
            prefill = None
            decode = float(obj["avg_ts"])
            agg = decode
        else:
            profile = f"pp{n_prompt}+tg{n_gen}"
            if n_depth:
                profile += f"+d{n_depth}"
            prefill = None
            decode = None
            agg = float(obj["avg_ts"])
        ctx = n_prompt + n_gen + n_depth
        experiment_id = f"llamabench-{model}-{profile}-{utc_now().replace(':', '').replace('-', '')}-{count}"
        record(
            {
                "experiment_id": experiment_id,
                "timestamp": utc_now(),
                "status": "ok",
                "model": model,
                "hf_id": hf_id,
                "revision": "",
                "quantization": quant,
                "engine": "llama.cpp",
                "engine_version": engine_version or obj.get("build_commit", ""),
                "profile": profile,
                "context_configured": ctx,
                "input_tokens": n_prompt,
                "output_tokens_requested": n_gen,
                "output_tokens_actual": n_gen,
                "concurrency_requested": 1,
                "engine_running_max": 1,
                "mode": "llama-bench",
                "mtp": "off",
                "draft_tokens": 0,
                "kv_cache": f"{obj.get('type_k', '')}/{obj.get('type_v', '')}",
                "attention": f"flash_attn={obj.get('flash_attn')}",
                "moe_backend": "",
                "aggregate_tok_s": agg,
                "decode_tok_s": decode,
                "prefill_tok_s": prefill,
                "e2e_per_request_mean": "",
                "e2e_per_request_median": "",
                "p95_latency_s": "",
                "ttft_p50_s": "",
                "ttft_p95_s": "",
                "completed": 1,
                "failed": 0,
                "duration_s": obj.get("test_time", ""),
                "peak_gpu_mem_mib": "",
                "notes": json.dumps(
                    {
                        "source": str(path),
                        "avg_ts": obj.get("avg_ts"),
                        "stddev_ts": obj.get("stddev_ts"),
                        "n_depth": n_depth,
                        "n_batch": obj.get("n_batch"),
                        "n_gpu_layers": obj.get("n_gpu_layers"),
                        "gpu_info": obj.get("gpu_info"),
                        "model_n_params": obj.get("model_n_params"),
                        "accounting": "llama-bench avg_ts is the isolated pp or tg rate for one sequence, not a mixed aggregate",
                    }
                ),
            }
        )
        count += 1
    return count


def ingest_batched(path: Path, model: str, hf_id: str, quant: str, engine_version: str, context: int) -> int:
    count = 0
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "speed_tg" not in obj:
            continue
        pp = int(obj["pp"])
        tg = int(obj["tg"])
        pl = int(obj["pl"])
        experiment_id = f"llamabatch-{model}-pp{pp}-tg{tg}-pl{pl}-{count}"
        record(
            {
                "experiment_id": experiment_id,
                "timestamp": utc_now(),
                "status": "ok",
                "model": model,
                "hf_id": hf_id,
                "revision": "",
                "quantization": quant,
                "engine": "llama.cpp",
                "engine_version": engine_version,
                "profile": f"pp{pp}+tg{tg}",
                "context_configured": context,
                "input_tokens": pp,
                "output_tokens_requested": tg,
                "output_tokens_actual": tg * pl,
                "concurrency_requested": pl,
                "engine_running_max": pl,
                "mode": "llama-batched-bench",
                "mtp": "off",
                "draft_tokens": 0,
                "kv_cache": "",
                "attention": f"flash_attn={obj.get('flash_attn')}",
                "moe_backend": "",
                "aggregate_tok_s": obj.get("speed_tg"),
                "decode_tok_s": obj.get("speed_tg"),
                "prefill_tok_s": obj.get("speed_pp"),
                "e2e_per_request_mean": (obj.get("speed_tg") / pl) if pl else "",
                "e2e_per_request_median": "",
                "p95_latency_s": obj.get("t"),
                "ttft_p50_s": obj.get("t_pp"),
                "ttft_p95_s": "",
                "completed": pl,
                "failed": 0,
                "duration_s": obj.get("t"),
                "peak_gpu_mem_mib": "",
                "notes": json.dumps(
                    {
                        "source": str(path),
                        "accounting": "speed_tg is pl*tg/t_tg, the aggregate decode tok/s across simultaneously decoded sequences. Prompts are random tokens, not chat traffic.",
                        "t_pp": obj.get("t_pp"),
                        "t_tg": obj.get("t_tg"),
                        "n_kv": obj.get("n_kv"),
                        "n_batch": obj.get("n_batch"),
                        "speed_e2e": obj.get("speed"),
                    }
                ),
            }
        )
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("bench", "batched"), required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--hf-id", required=True)
    parser.add_argument("--quant", required=True)
    parser.add_argument("--engine-version", default="")
    parser.add_argument("--context", type=int, default=0)
    args = parser.parse_args()
    path = Path(args.path)
    if args.kind == "bench":
        n = ingest_bench(path, args.model, args.hf_id, args.quant, args.engine_version)
    else:
        n = ingest_batched(path, args.model, args.hf_id, args.quant, args.engine_version, args.context)
    print(f"ingested {n} rows from {path}")


if __name__ == "__main__":
    main()
