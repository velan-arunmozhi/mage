#!/usr/bin/env python3
"""Executable coding comparison. Imports the round-2 tasks and adds a few more."""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_round2 import TASKS, check
from record import record

ROOT = Path("/scratch/scholar/billin19/gb10-inference-bench")

EXTRA = [
    {
        "name": "py-unique-sorted",
        "prompt": textwrap.dedent("""
            Write unique_sorted(nums) that returns a new sorted list of the unique integers in nums.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert unique_sorted([3, 1, 2, 1, 3]) == [1, 2, 3]
            assert unique_sorted([]) == []
            assert unique_sorted([5, 5]) == [5]
        """),
    },
    {
        "name": "py-window-max",
        "prompt": textwrap.dedent("""
            Write max_window(nums, k) that returns the maximum of each contiguous window of length k.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert max_window([1, 3, 2, 5, 4], 3) == [3, 5, 5]
            assert max_window([1], 1) == [1]
            assert max_window([4, 2], 2) == [4]
        """),
    },
    {
        "name": "py-counter",
        "prompt": textwrap.dedent("""
            Fix the bug. tally(words) should return a dict of word counts.
            Return only a python code block.
            Current code:
            def tally(words):
                counts = {}
                for word in words:
                    counts[word] = counts.get(word, 1) + 1
                return counts
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert tally(["a", "b", "a"]) == {"a": 2, "b": 1}
            assert tally([]) == {}
            assert tally(["z"]) == {"z": 1}
        """),
    },
    {
        "name": "tool-search",
        "prompt": textwrap.dedent("""
            Reply with only this JSON object and no other JSON:
            {"name":"search","arguments":{"query":"kv cache","limit":5}}
        """).strip(),
        "check": "json-exact",
        "expect": {"name": "search", "arguments": {"query": "kv cache", "limit": 5}},
    },
]


def chat(base: str, model: str, prompt: str, max_tokens: int, thinking: str = "server-default") -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if thinking in {"low", "medium", "high"}:
        body["messages"].insert(0, {"role": "system", "content": f"Reasoning: {thinking}"})
    elif thinking == "off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode())
    message = (data.get("choices") or [{}])[0].get("message") or {}
    text = "\n".join(str(message.get(key) or "") for key in ("content", "reasoning", "reasoning_content"))
    usage = data.get("usage") or {}
    return {"text": text, "usage": usage, "elapsed_s": time.perf_counter() - started}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--thinking", default="server-default")
    parser.add_argument("--engine", default="vllm")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    tasks = list(TASKS) + EXTRA
    rows = []
    passed = 0
    skipped = 0
    total_tokens = 0
    total_time = 0.0
    for task in tasks:
        print(f"TASK {args.tag} {task['name']}", flush=True)
        try:
            result = chat(args.base_url.rstrip("/"), args.model, task["prompt"], args.max_tokens)
            if task["check"] == "json-exact":
                from quality_round2 import extract_json
                try:
                    obj = extract_json(result["text"])
                    ok = obj == task["expect"]
                    detail = json.dumps(obj)[:400]
                except Exception as exc:
                    ok, detail = False, str(exc)
            else:
                ok, detail = check(task, result["text"])
            err = None
        except Exception as exc:  # noqa: BLE001
            result = {"usage": {}, "elapsed_s": 0.0}
            ok, detail, err = False, "", f"{type(exc).__name__}: {exc}"
        if detail in {"node-missing", "go-missing"}:
            skipped += 1
            ok = False
        else:
            passed += int(ok)
        usage = result.get("usage") or {}
        tokens = int(usage.get("completion_tokens") or 0)
        elapsed = float(result.get("elapsed_s") or 0)
        total_tokens += tokens
        total_time += elapsed
        print(f"  ok={ok} skip={detail in {'node-missing','go-missing'}} tokens={tokens} elapsed={elapsed:.1f} {detail[:160]}", flush=True)
        rows.append({"name": task["name"], "ok": ok, "detail": detail, "error": err, "usage": usage, "elapsed_s": elapsed})
        (ROOT / "raw" / f"quality3-{args.tag}-{task['name']}.json").write_text(json.dumps(rows[-1])[:80000], encoding="utf-8")
    attempted = len(tasks) - skipped
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record({
        "experiment_id": f"quality3-{args.tag}-{stamp}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
        "model": args.model,
        "hf_id": args.model,
        "quantization": "NVFP4" if "Qwen3.6" in args.model or "ornith" in args.model else "Q4_K_M",
        "engine": args.engine,
        "engine_version": args.engine,
        "profile": "quality-16",
        "context_configured": 131072,
        "concurrency_requested": 1,
        "mode": "quality",
        "mtp": args.tag,
        "output_tokens_actual": total_tokens,
        "duration_s": total_time,
        "completed": passed,
        "failed": attempted - passed,
        "notes": json.dumps({
            "thinking": args.thinking,
            "passed": passed,
            "attempted": attempted,
            "skipped": skipped,
            "tasks_per_minute": (passed / total_time * 60) if total_time else None,
            "tasks": [row["name"] + ":" + str(row["ok"]) for row in rows],
        }),
    })
    print(f"QUALITY {args.tag} {passed}/{attempted} skipped={skipped} minutes={total_time/60:.2f}", flush=True)


if __name__ == "__main__":
    main()
