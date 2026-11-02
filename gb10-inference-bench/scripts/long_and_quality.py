#!/usr/bin/env python3
"""One filled long prompt and a handful of checked coding questions."""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import record

BASE = "http://127.0.0.1:8000"
MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"
ROOT = Path("/scratch/scholar/billin19/gb10-inference-bench")


def post(path: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat(content: str, max_tokens: int, timeout: float) -> dict:
    started = time.perf_counter()
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    try:
        data = post("/v1/chat/completions", body, timeout)
        err = None
    except Exception as exc:  # noqa: BLE001
        data = {}
        err = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    message = ((data.get("choices") or [{}])[0].get("message") or {}) if data else {}
    text = " ".join(
        str(message.get(key) or "")
        for key in ("content", "reasoning", "reasoning_content")
    )
    usage = data.get("usage") or {}
    return {
        "text": text,
        "usage": usage,
        "elapsed_s": elapsed,
        "error": err,
    }


def sentence(i: int) -> str:
    return (
        f"Note {i}: buffer region {i % 13} checksum {(i * 17) % 9973} "
        f"status {(i * 5) % 409} trace T{(i * 13) % 10007}."
    )


def build_long(target: int) -> str:
    # Grow by measured token count. The secret sits after the filler.
    parts = []
    count = 4000
    text = ""
    tokens = 0
    while tokens < target and count < 200000:
        parts = [sentence(i) for i in range(count)]
        text = "\n".join(parts)
        try:
            obj = post("/tokenize", {"prompt": text}, 120)
            tokens = int(obj.get("count") or len(obj.get("tokens") or []))
        except Exception:
            tokens = count * 12
        print(f"build count={count} tokens={tokens}", flush=True)
        if tokens < target:
            count = int(count * target / max(tokens, 1)) + 100
        else:
            break
    return text + "\nThe repository passphrase is ORCHID-19.\n" + "\n".join(sentence(i) for i in range(count, count + 20))


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("building long prompt", flush=True)
    filler = build_long(100000)
    question = filler + "\nWhat is the repository passphrase? Reply with the passphrase only."
    print("sending long request", flush=True)
    long = chat(question, 256, 1800)
    (ROOT / "raw" / "qwen36-long-retrieval.json").write_text(json.dumps(long)[:200000], encoding="utf-8")
    passed = "ORCHID-19" in long["text"]
    prompt_tokens = (long["usage"] or {}).get("prompt_tokens")
    completion = (long["usage"] or {}).get("completion_tokens") or 0
    print(
        f"LONG passed={passed} prompt={prompt_tokens} out={completion} "
        f"elapsed={long['elapsed_s']:.1f} err={long['error']}",
        flush=True,
    )
    record(
        {
            "experiment_id": f"qwen36-long-retrieval-{stamp}",
            "timestamp": stamp,
            "status": "ok" if long["error"] is None else "failed",
            "model": MODEL,
            "hf_id": MODEL,
            "quantization": "NVFP4",
            "engine": "vllm",
            "engine_version": "vllm 0.28.0 cuda-graphs",
            "profile": "long-retrieval",
            "context_configured": 131072,
            "input_tokens": prompt_tokens,
            "output_tokens_requested": 256,
            "output_tokens_actual": completion,
            "concurrency_requested": 1,
            "mode": "single",
            "mtp": "off",
            "kv_cache": "fp8",
            "attention": "flashinfer",
            "moe_backend": "marlin",
            "aggregate_tok_s": (completion / long["elapsed_s"]) if long["elapsed_s"] else None,
            "completed": 0 if long["error"] else 1,
            "failed": 1 if long["error"] else 0,
            "duration_s": long["elapsed_s"],
            "notes": json.dumps({"passphrase_found": passed, "error": long["error"]}),
        }
    )

    tasks = [
        ("sum-evens", "What does this print? def f(n):\n s=0\n for i in range(1,n):\n  if i%2==0: s+=i\n return s\nprint(f(10))\nReply with the integer only.", "20"),
        ("product", "What is 12*17? Reply with the integer only.", "204"),
        ("stairs", "Number of ways to climb 10 stairs taking 1 or 2 steps. Reply with the integer only.", "89"),
        ("tool", 'Return only JSON: {"name":"read_file","arguments":{"path":"main.py"}}', '"path": "main.py"'),
        ("off-by-one", "for i in range(5): print(i)  How many lines are printed? Reply with the integer only.", "5"),
    ]
    correct = 0
    for name, prompt, expect in tasks:
        result = chat(prompt, 512, 300)
        ok = expect in result["text"]
        correct += int(ok)
        print(f"TASK {name} ok={ok} elapsed={result['elapsed_s']:.1f} usage={result['usage']}", flush=True)
        (ROOT / "raw" / f"quality-{name}.json").write_text(json.dumps(result)[:50000], encoding="utf-8")
    record(
        {
            "experiment_id": f"qwen36-quality-{stamp}",
            "timestamp": stamp,
            "status": "ok",
            "model": MODEL,
            "hf_id": MODEL,
            "quantization": "NVFP4",
            "engine": "vllm",
            "engine_version": "vllm 0.28.0 cuda-graphs",
            "profile": "quality-5",
            "context_configured": 131072,
            "concurrency_requested": 1,
            "mode": "quality",
            "mtp": "off",
            "completed": correct,
            "failed": len(tasks) - correct,
            "notes": json.dumps({"passed": correct, "attempted": len(tasks)}),
        }
    )
    print(f"QUALITY {correct}/{len(tasks)}", flush=True)


if __name__ == "__main__":
    main()
