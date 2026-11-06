#!/usr/bin/env python3
"""OpenAI-compatible streaming benchmark client.

Aggregate throughput counts completion tokens from requests that were launched
after warmup and that finished successfully, divided by the wall time from the
start of the measured window through the last counted completion (drain
included). Incomplete requests are not counted as successes.

Per-request decode tok/s is (completion_tokens - 1) / (end - ttft) when TTFT
is known. That is not an aggregate decode rate. Aggregate decode rate is
reported only when every successful request has a TTFT, as
sum(completion_tokens - 1) / sum(decode_seconds), which is a concurrency-weighted
mean of per-request decode rates, not the engine's internal decode counter.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import threading
import time
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import record

PROFILES = {
    "A": (1024, 512),
    "B": (8192, 1024),
    "C": (32768, 1024),
    "D": (120000, 1024),
    "E128": (127000, 1024),
    "E262": (131072, 2048),
}

MODES = ("read", "write", "append", "lock", "flush", "index", "merge", "scan")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def sentence(index: int) -> str:
    mode = MODES[index % len(MODES)]
    return (
        f"Function f{index} in module m{index % 97} handles the {mode} path for region {index % 13}. "
        f"It checks checksum {(index * 17) % 9973}, calls helper h{(index * 3) % 80} with limit {(index % 23) + 1}, "
        f"and records trace id T{(index * 13) % 10007} before returning status {(index * 5) % 409} "
        f"to the caller that owns buffer slice {index % 64}."
    )


class Client:
    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self.base = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.ignore_eos = True
        self.min_tokens = True
        self.stream_usage = True
        self.system: str | None = None
        self._token_cache: dict[str, int] = {}

    def _request(self, method: str, path: str, payload: dict | None, timeout: float | None = None) -> tuple[int, bytes]:
        url = self.base + path
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return exc.code, body

    def tokenize(self, text: str) -> int | None:
        cached = self._token_cache.get(text)
        if cached is not None:
            return cached
        attempts = [
            ("/tokenize", {"content": text, "add_special": False, "parse_special": False}),
            ("/tokenize", {"prompt": text}),
            ("/v1/tokenize", {"model": self.model, "prompt": text}),
        ]
        for path, payload in attempts:
            code, raw = self._request("POST", path, payload, timeout=120)
            if code != 200:
                continue
            try:
                obj = json.loads(raw.decode())
            except json.JSONDecodeError:
                continue
            count = None
            if isinstance(obj, dict):
                if "count" in obj and isinstance(obj["count"], int):
                    count = obj["count"]
                elif "tokens" in obj and isinstance(obj["tokens"], list):
                    count = len(obj["tokens"])
                elif "token_ids" in obj and isinstance(obj["token_ids"], list):
                    count = len(obj["token_ids"])
            if count is not None:
                self._token_cache[text] = count
                return count
        return None

    def build_prompt(self, target_tokens: int, seed: int) -> tuple[str, int | None]:
        def join(count: int) -> str:
            return "\n".join(sentence(seed + i) for i in range(count))

        one = self.tokenize(sentence(seed))
        if one is None or one <= 0:
            # Character fallback is only a construction aid. Callers must replace
            # this with measured prompt tokens from the API usage field.
            approx = max(1, target_tokens * 4)
            return join(max(1, target_tokens // 40))[:approx], None
        hi = max(2, int(target_tokens / one) + 2)
        hi_text = join(hi)
        hi_n = self.tokenize(hi_text)
        guard = 0
        while hi_n is not None and hi_n < target_tokens and guard < 8:
            hi *= 2
            hi_text = join(hi)
            hi_n = self.tokenize(hi_text)
            guard += 1
        lo = 1
        best_n = 0
        best_count = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            n = self.tokenize(join(mid))
            if n is None:
                break
            if n <= target_tokens:
                best_n = n
                best_count = mid
                lo = mid + 1
            else:
                hi = mid - 1
        text = join(best_count)
        extra = 0
        while best_n < target_tokens and extra < 8:
            best_count += 1
            extra += 1
            text = join(best_count)
            n = self.tokenize(text)
            if n is None:
                break
            if n > target_tokens and best_n > 0:
                best_count -= 1
                text = join(best_count)
                break
            best_n = n
        measured = self.tokenize(text)
        return text, measured

    def probe_capabilities(self) -> None:
        content, _ = self.build_prompt(32, seed=1)
        body = self._body(content, max_tokens=1, stream=False)
        code, raw = self._request("POST", "/v1/chat/completions", body, timeout=180)
        if code == 400:
            self.ignore_eos = False
            self.min_tokens = False
            self.stream_usage = False
            body = self._body(content, max_tokens=1, stream=False)
            code, raw = self._request("POST", "/v1/chat/completions", body, timeout=180)
        if code != 200:
            raise RuntimeError(f"capability probe failed HTTP {code}: {raw[:500]!r}")

    def _body(self, content: str, max_tokens: int, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": content})
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": stream,
        }
        if self.ignore_eos:
            body["ignore_eos"] = True
        if self.min_tokens:
            body["min_tokens"] = max_tokens
        if stream and self.stream_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    def one(self, content: str, max_tokens: int) -> dict[str, Any]:
        body = self._body(content, max_tokens, stream=True)
        url = self.base + "/v1/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream")
        started = time.perf_counter()
        ttft = None
        usage = None
        text_parts: list[str] = []
        error = None
        finish = None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
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
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    piece = (
                        delta.get("content")
                        or delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or ""
                    )
                    if piece and ttft is None:
                        ttft = time.perf_counter() - started
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                    if choice.get("finish_reason"):
                        finish = choice["finish_reason"]
        except Exception as exc:  # noqa: BLE001 - record and continue the sweep
            error = f"{type(exc).__name__}: {exc}"
        ended = time.perf_counter()
        completion_tokens = None
        prompt_tokens = None
        reasoning_tokens = 0
        if isinstance(usage, dict):
            completion_tokens = usage.get("completion_tokens")
            prompt_tokens = usage.get("prompt_tokens")
            details = usage.get("completion_tokens_details") or {}
            reasoning_tokens = int(details.get("reasoning_tokens") or 0)
        text = "".join(text_parts)
        if completion_tokens is None and text and error is None:
            completion_tokens = self.tokenize(text)
        latency = ended - started
        decode_s = None
        decode_tok_s = None
        if ttft is not None and completion_tokens is not None and completion_tokens > 1:
            decode_s = max(ended - (started + ttft), 1e-6)
            decode_tok_s = (completion_tokens - 1) / decode_s
        e2e_tok_s = None
        if completion_tokens and latency > 0:
            e2e_tok_s = completion_tokens / latency
        return {
            "ok": error is None and completion_tokens is not None,
            "error": error,
            "latency_s": latency,
            "ttft_s": ttft,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens or 0,
            "reasoning_tokens": reasoning_tokens,
            "finish_reason": finish,
            "decode_tok_s": decode_tok_s,
            "e2e_tok_s": e2e_tok_s,
            "text_chars": len(text),
        }


def sample_metrics(base: str) -> dict[str, float]:
    url = base.rstrip("/") + "/metrics"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            text = resp.read().decode(errors="replace")
    except Exception:
        return {}
    interesting = (
        "num_requests_running",
        "num_requests_waiting",
        "gpu_cache_usage",
        "kv_cache_usage",
        "spec_decode",
        "accepted",
    )
    found: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not any(key in line for key in interesting):
            continue
        bits = line.split()
        if len(bits) < 2:
            continue
        try:
            found[bits[0]] = float(bits[-1])
        except ValueError:
            continue
    return found


def summarize(requests: list[dict[str, Any]], started: float, ended: float) -> dict[str, Any]:
    ok = [item for item in requests if item.get("ok")]
    failed = [item for item in requests if not item.get("ok")]
    out_tokens = sum(int(item.get("completion_tokens") or 0) for item in ok)
    elapsed = max(ended - started, 1e-6)
    latencies = [float(item["latency_s"]) for item in ok]
    ttfts = [float(item["ttft_s"]) for item in ok if item.get("ttft_s") is not None]
    e2e = [float(item["e2e_tok_s"]) for item in ok if item.get("e2e_tok_s")]
    decode = [float(item["decode_tok_s"]) for item in ok if item.get("decode_tok_s")]
    prompt_tokens = [int(item["prompt_tokens"]) for item in ok if item.get("prompt_tokens")]
    decode_num = 0
    decode_den = 0.0
    for item in ok:
        tokens = int(item.get("completion_tokens") or 0)
        ttft = item.get("ttft_s")
        if tokens > 1 and ttft is not None:
            decode_num += tokens - 1
            decode_den += max(float(item["latency_s"]) - float(ttft), 1e-6)
    return {
        "completed": len(ok),
        "failed": len(failed),
        "output_tokens_actual": out_tokens,
        "duration_s": elapsed,
        "aggregate_tok_s": out_tokens / elapsed,
        "decode_tok_s": (decode_num / decode_den) if decode_den else None,
        "e2e_per_request_mean": statistics.fmean(e2e) if e2e else None,
        "e2e_per_request_median": statistics.median(e2e) if e2e else None,
        "p95_latency_s": percentile(latencies, 0.95),
        "ttft_p50_s": percentile(ttfts, 0.50),
        "ttft_p95_s": percentile(ttfts, 0.95),
        "input_tokens": statistics.fmean(prompt_tokens) if prompt_tokens else None,
        "reasoning_tokens": sum(int(item.get("reasoning_tokens") or 0) for item in ok),
        "prefill_tok_s": None,
        "errors": [item.get("error") for item in failed[:5]],
    }


def run_closed_loop(client: Client, content: str, max_tokens: int, concurrency: int, duration: float, base: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    lock = threading.Lock()
    running = {"now": 0, "max": 0}
    metric_max = {"running": 0.0, "waiting": 0.0}
    stop_sample = threading.Event()

    def sampler() -> None:
        while not stop_sample.is_set():
            metrics = sample_metrics(base)
            for key, value in metrics.items():
                if key.endswith("num_requests_running") or "num_requests_running" in key:
                    metric_max["running"] = max(metric_max["running"], value)
                if "num_requests_waiting" in key:
                    metric_max["waiting"] = max(metric_max["waiting"], value)
            stop_sample.wait(1.0)

    def worker(worker_id: int) -> None:
        seq = 0
        while True:
            if time.perf_counter() >= deadline:
                return
            seq += 1
            # Unique tail so prefix caching cannot collapse distinct requests.
            # Unique prefix so slot LCP / prefix cache does not reuse the body.
            prompt = (
                f"Case {worker_id}-{seq} salt {(worker_id * 10007 + seq * 97) % 1000003}. "
                f"Do not reuse prior context.\n{content}\nContinue the implementation.\n"
            )
            with lock:
                running["now"] += 1
                running["max"] = max(running["max"], running["now"])
            item = client.one(prompt, max_tokens)
            with lock:
                running["now"] -= 1
                results.append(item)

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    sampler_thread.start()
    started = time.perf_counter()
    deadline = started + duration
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ended = time.perf_counter()
    stop_sample.set()
    summary = summarize(results, started, ended)
    summary["client_inflight_max"] = running["max"]
    summary["engine_running_max"] = metric_max["running"] or None
    summary["engine_waiting_max"] = metric_max["waiting"] or None
    return summary, results


def run_burst(client: Client, content: str, max_tokens: int, concurrency: int, base: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    results: list[dict[str, Any] | None] = [None] * concurrency
    start_gate = threading.Barrier(concurrency)

    def worker(index: int) -> None:
        prompt = (
            f"Burst case {index} salt {(index * 7919) % 1000003}. Do not reuse prior context.\n"
            f"{content}\nContinue the implementation.\n"
        )
        start_gate.wait()
        results[index] = client.one(prompt, max_tokens)

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ended = time.perf_counter()
    finished = [item for item in results if item is not None]
    summary = summarize(finished, started, ended)
    summary["client_inflight_max"] = concurrency
    summary["engine_running_max"] = None
    summary["engine_waiting_max"] = None
    metrics = sample_metrics(base)
    for key, value in metrics.items():
        if "num_requests_running" in key:
            summary["engine_running_max"] = value
    return summary, finished


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--hf-id", default="")
    parser.add_argument("--revision", default="")
    parser.add_argument("--quantization", default="")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--engine-version", default="")
    parser.add_argument("--profiles", default="A,B")
    parser.add_argument("--concurrencies", default="1,2,4,8")
    parser.add_argument("--mode", choices=("sustained", "burst"), default="sustained")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--context-configured", type=int, default=0)
    parser.add_argument("--kv-cache", default="")
    parser.add_argument("--attention", default="")
    parser.add_argument("--moe-backend", default="")
    parser.add_argument("--mtp", default="off")
    parser.add_argument("--draft-tokens", type=int, default=0)
    parser.add_argument("--thinking", default="off")
    parser.add_argument("--raw-dir", default="")
    args = parser.parse_args()

    client = Client(args.base_url, args.model, args.timeout)
    if args.thinking in {"low", "medium", "high"}:
        client.system = f"Reasoning: {args.thinking}"
    client.probe_capabilities()
    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    concs = [int(item) for item in args.concurrencies.split(",") if item.strip()]
    raw_dir = args.raw_dir or os.environ.get("BENCH_ROOT", "/scratch/scholar/billin19/gb10-inference-bench") + "/raw"

    for profile in profiles:
        if profile not in PROFILES:
            raise SystemExit(f"unknown profile {profile}")
        target_in, target_out = PROFILES[profile]
        content, content_tokens = client.build_prompt(target_in, seed=1000 + target_in)
        print(f"PROFILE {profile} content_tokens={content_tokens} target_in={target_in} target_out={target_out}", flush=True)
        for _ in range(args.warmup):
            warm = client.one(content + "\nWarmup marker.\n", min(32, target_out))
            print(f"WARMUP ok={warm['ok']} prompt={warm['prompt_tokens']} out={warm['completion_tokens']} err={warm['error']}", flush=True)
        for concurrency in concs:
            print(f"RUN profile={profile} c={concurrency} mode={args.mode}", flush=True)
            if args.mode == "sustained":
                summary, details = run_closed_loop(client, content, target_out, concurrency, args.duration, args.base_url)
            else:
                summary, details = run_burst(client, content, target_out, concurrency, args.base_url)
            experiment_id = f"{args.tag}-{profile}-c{concurrency}-{args.mode}-{utc_now().replace(':', '').replace('-', '')}"
            notes = {
                "thinking": args.thinking,
                "reasoning_tokens": summary.get("reasoning_tokens"),
                "engine_waiting_max": summary.get("engine_waiting_max"),
                "accounting": "completed_output_tokens / (last_completion - window_start), drain included, warmup excluded",
                "content_tokens_pretokenize": content_tokens,
                "ignore_eos": client.ignore_eos,
                "min_tokens": client.min_tokens,
                "errors": summary.get("errors"),
                "client_inflight_max": summary.get("client_inflight_max"),
            }
            row = {
                "experiment_id": experiment_id,
                "timestamp": utc_now(),
                "status": "ok" if summary["completed"] else "failed",
                "model": args.model,
                "hf_id": args.hf_id or args.model,
                "revision": args.revision,
                "quantization": args.quantization,
                "engine": args.engine,
                "engine_version": args.engine_version,
                "profile": profile,
                "context_configured": args.context_configured,
                "input_tokens": summary.get("input_tokens"),
                "output_tokens_requested": target_out,
                "output_tokens_actual": summary.get("output_tokens_actual"),
                "concurrency_requested": concurrency,
                "engine_running_max": summary.get("engine_running_max"),
                "mode": args.mode,
                "mtp": args.mtp,
                "draft_tokens": args.draft_tokens,
                "kv_cache": args.kv_cache,
                "attention": args.attention,
                "moe_backend": args.moe_backend,
                "aggregate_tok_s": summary.get("aggregate_tok_s"),
                "decode_tok_s": summary.get("decode_tok_s"),
                "prefill_tok_s": summary.get("prefill_tok_s"),
                "e2e_per_request_mean": summary.get("e2e_per_request_mean"),
                "e2e_per_request_median": summary.get("e2e_per_request_median"),
                "p95_latency_s": summary.get("p95_latency_s"),
                "ttft_p50_s": summary.get("ttft_p50_s"),
                "ttft_p95_s": summary.get("ttft_p95_s"),
                "completed": summary.get("completed"),
                "failed": summary.get("failed"),
                "duration_s": summary.get("duration_s"),
                "peak_gpu_mem_mib": "",
                "notes": json.dumps(notes),
            }
            record(row, summary=row["status"] == "ok")
            detail_path = os.path.join(raw_dir, experiment_id + ".json")
            os.makedirs(raw_dir, exist_ok=True)
            with open(detail_path, "w", encoding="utf-8") as fh:
                json.dump({"summary": row, "requests": details}, fh)
            print(
                f"RESULT {experiment_id} agg={row['aggregate_tok_s']:.2f} tok/s "
                f"completed={row['completed']} failed={row['failed']} "
                f"in_tok={row['input_tokens']} out_tok={row['output_tokens_actual']} "
                f"ttft_p50={row['ttft_p50_s']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
