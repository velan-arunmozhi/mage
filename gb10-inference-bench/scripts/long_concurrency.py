#!/usr/bin/env python3
"""Concurrent filled long-context requests with a retrieval check."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import record

ROOT = Path("/scratch/scholar/billin19/gb10-inference-bench")


def post(base: str, path: str, payload: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except Exception as exc:
        body = getattr(exc, "read", lambda: b"")()
        if callable(body):
            try:
                body = body()
            except Exception:
                body = str(exc).encode()
        return getattr(exc, "code", 0) or 0, body or str(exc).encode()


def token_count(base: str, text: str) -> int | None:
    code, raw = post(base, "/tokenize", {"prompt": text}, 180)
    if code != 200:
        code, raw = post(base, "/tokenize", {"content": text, "add_special": False}, 180)
    if code != 200:
        return None
    try:
        obj = json.loads(raw.decode())
    except json.JSONDecodeError:
        return None
    if isinstance(obj.get("count"), int):
        return obj["count"]
    if isinstance(obj.get("tokens"), list):
        return len(obj["tokens"])
    return None


def sentence(i: int, salt: int) -> str:
    return (
        f"Log {salt}-{i}: region {i % 17} checksum {(i * 19 + salt) % 9973} "
        f"owner {(i * 3) % 80} state {(i + salt) % 11}."
    )


def build_prompt(base: str, target: int, salt: int, code: str) -> tuple[str, int | None]:
    count = 3500
    text = ""
    tokens = 0
    for _ in range(8):
        body = [sentence(i, salt) for i in range(count)]
        # Place the secret after a unique prefix and before a unique suffix.
        pivot = max(1, count // 2)
        body.insert(pivot, f"The retrieval code for slot {salt} is {code}.")
        text = f"Slot {salt} document begins.\n" + "\n".join(body) + f"\nSlot {salt} document ends.\nWhat is the retrieval code for slot {salt}? Reply with the code only."
        tokens = token_count(base, text) or 0
        print(f"build salt={salt} sentences={count} tokens={tokens}", flush=True)
        if tokens == 0:
            break
        if abs(tokens - target) < 4000:
            break
        count = max(500, int(count * target / tokens))
    return text, tokens or None


def one(base: str, model: str, content: str, max_tokens: int, timeout: float, min_tokens: int, system: str = "") -> dict:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "min_tokens": min_tokens,
        "ignore_eos": True,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    started = time.perf_counter()
    ttft = None
    usage = None
    parts: list[str] = []
    error = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {})
                piece = delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning") or ""
                if piece and ttft is None:
                    ttft = time.perf_counter() - started
                if delta.get("content"):
                    parts.append(delta["content"])
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    parts.append(delta.get("reasoning_content") or delta.get("reasoning") or "")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    text = "".join(parts)
    completion = (usage or {}).get("completion_tokens")
    prompt = (usage or {}).get("prompt_tokens")
    return {
        "ok": error is None and completion is not None,
        "error": error,
        "text": text,
        "prompt_tokens": prompt,
        "completion_tokens": completion or 0,
        "ttft_s": ttft,
        "latency_s": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--mtp", required=True)
    parser.add_argument("--draft-tokens", type=int, default=0)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--target-tokens", type=int, default=120000)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--min-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--system", default="")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    codes = [f"CODE-{args.mtp}-{args.concurrency}-{i}-{1000 + i * 17}" for i in range(args.concurrency)]
    prompts = []
    for i, code in enumerate(codes):
        text, n = build_prompt(base, args.target_tokens, salt=100 + i + args.concurrency * 10, code=code)
        prompts.append((text, n, code))
    results: list[dict | None] = [None] * args.concurrency
    gate = threading.Barrier(args.concurrency)

    def worker(index: int) -> None:
        gate.wait()
        results[index] = one(base, args.model, prompts[index][0], args.max_tokens, args.timeout, args.min_tokens, args.system)

    running_max = {"n": 0.0, "wait": 0.0, "kv": 0.0}
    stop_sample = threading.Event()

    def sampler() -> None:
        while not stop_sample.is_set():
            try:
                with urllib.request.urlopen(base + "/metrics", timeout=2) as resp:
                    text = resp.read().decode(errors="replace")
            except Exception:
                stop_sample.wait(1.0)
                continue
            for line in text.splitlines():
                if not line or line.startswith("#"):
                    continue
                bits = line.split()
                if len(bits) < 2:
                    continue
                try:
                    value = float(bits[-1])
                except ValueError:
                    continue
                if "num_requests_running" in bits[0]:
                    running_max["n"] = max(running_max["n"], value)
                elif "num_requests_waiting" in bits[0]:
                    running_max["wait"] = max(running_max["wait"], value)
                elif "kv_cache_usage" in bits[0] or "gpu_cache_usage" in bits[0]:
                    running_max["kv"] = max(running_max["kv"], value)
            stop_sample.wait(0.5)

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()
    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    stop_sample.set()
    sampler_thread.join(timeout=2)
    elapsed = time.perf_counter() - started
    done = [item for item in results if item and item.get("ok")]
    failed = args.concurrency - len(done)
    out_tokens = sum(int(item.get("completion_tokens") or 0) for item in done)
    hits = 0
    for item, (_, _, code) in zip(results, prompts):
        if item and code in (item.get("text") or ""):
            hits += 1
            item["retrieved"] = True
        elif item:
            item["retrieved"] = False
    prompt_tokens = [int(item["prompt_tokens"]) for item in done if item.get("prompt_tokens")]
    ttfts = [float(item["ttft_s"]) for item in done if item.get("ttft_s") is not None]
    decode_rates = []
    prefill_rates = []
    for item in done:
        ttft = item.get("ttft_s")
        tokens = int(item.get("completion_tokens") or 0)
        latency = float(item.get("latency_s") or 0)
        prompts_n = item.get("prompt_tokens")
        if ttft and tokens > 1 and latency > ttft:
            decode_rates.append((tokens - 1) / (latency - ttft))
        if ttft and prompts_n:
            prefill_rates.append(int(prompts_n) / float(ttft))
    decode_mean = sum(decode_rates) / len(decode_rates) if decode_rates else None
    prefill_mean = sum(prefill_rates) / len(prefill_rates) if prefill_rates else None
    decode_window = None
    if ttfts:
        first_decode = min(ttfts)
        last_end = max(float(item["latency_s"]) for item in done)
        if last_end > first_decode:
            decode_window = out_tokens / (last_end - first_decode)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    experiment_id = f"long-{args.mtp}-c{args.concurrency}-{stamp}"
    row = {
        "experiment_id": experiment_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok" if done else "failed",
        "model": args.model,
        "hf_id": args.model,
        "quantization": "NVFP4",
        "engine": "vllm",
        "engine_version": "vllm 0.28.0 cuda-graphs",
        "profile": "long-120k",
        "context_configured": 131072,
        "input_tokens": (sum(prompt_tokens) / len(prompt_tokens)) if prompt_tokens else None,
        "output_tokens_requested": args.max_tokens,
        "output_tokens_actual": out_tokens,
        "concurrency_requested": args.concurrency,
        "engine_running_max": running_max["n"] or None,
        "mode": "burst-filled",
        "mtp": args.mtp,
        "draft_tokens": args.draft_tokens,
        "kv_cache": "fp8",
        "attention": "flashinfer",
        "moe_backend": "marlin",
        "aggregate_tok_s": out_tokens / elapsed if elapsed else None,
        "decode_tok_s": decode_mean,
        "prefill_tok_s": prefill_mean,
        "ttft_p50_s": sorted(ttfts)[len(ttfts) // 2] if ttfts else None,
        "completed": len(done),
        "failed": failed,
        "duration_s": elapsed,
        "notes": json.dumps({
            "retrieved": hits,
            "prompt_tokens": prompt_tokens,
            "errors": [item.get("error") for item in results if item and item.get("error")],
            "accounting": "e2e aggregate is completion tokens / full wall. decode_tok_s is the mean per-request (completion-1)/(latency-ttft). decode_window_tok_s is all completion tokens / (last finish - earliest TTFT).",
            "decode_window_tok_s": decode_window,
            "min_tokens": args.min_tokens,
            "engine_waiting_max": running_max["wait"],
            "kv_cache_usage_max": running_max["kv"],
        }),
    }
    record(row, summary=row["status"] == "ok")
    detail = ROOT / "raw" / f"{experiment_id}.json"
    detail.write_text(json.dumps({
        "summary": row,
        "codes": codes,
        "requests": [{k: v for k, v in (item or {}).items() if k != "text"} | {"text_tail": (item or {}).get("text", "")[-400:]} for item in results],
    }), encoding="utf-8")
    print(
        f"LONG {args.mtp} c={args.concurrency} completed={len(done)} failed={failed} "
        f"retrieved={hits} e2e={row['aggregate_tok_s']} decode_mean={decode_mean} "
        f"decode_window={decode_window} prefill_mean={prefill_mean} elapsed={elapsed:.1f} "
        f"running={running_max['n']} waiting={running_max['wait']} prompts={prompt_tokens}",
        flush=True,
    )


if __name__ == "__main__":
    main()
