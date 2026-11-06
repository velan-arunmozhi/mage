#!/usr/bin/env python3
"""Harder checked coding tasks for Qwen3.6 versus Qwen3.5-2B."""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from quality_round3 import chat, ROOT
from quality_round2 import check, extract_json
from record import record

TASKS = [
    {
        "name": "multifile-discount",
        "prompt": textwrap.dedent("""
            Two modules. Fix the bug in pricing.py. checkout.py is correct and must stay unchanged.
            Return only the corrected pricing.py in one python block named so that the tests can exec both.
            Put both modules in one python block, with pricing functions defined before checkout.

            pricing.py:
            def unit_price(cents, qty, discount_bp):
                # discount_bp is basis points, 10000 = 100%.
                gross = cents * qty
                return gross - gross * discount_bp // 1000

            checkout.py uses unit_price. A 10% discount is discount_bp=1000.
            Tests:
            unit_price(500, 2, 1000) == 900
            unit_price(500, 2, 0) == 1000
            unit_price(100, 1, 10000) == 0
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert unit_price(500, 2, 1000) == 900
            assert unit_price(500, 2, 0) == 1000
            assert unit_price(100, 1, 10000) == 0
            assert unit_price(250, 3, 2000) == 600
        """),
    },
    {
        "name": "lis-length",
        "prompt": textwrap.dedent("""
            Write lis_length(nums) returning the length of the longest strictly increasing subsequence.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert lis_length([10, 9, 2, 5, 3, 7, 101, 18]) == 4
            assert lis_length([0, 1, 0, 3, 2, 3]) == 4
            assert lis_length([7, 7, 7]) == 1
            assert lis_length([]) == 0
        """),
    },
    {
        "name": "repo-drop-last",
        "prompt": textwrap.dedent("""
            This repository has one bug: the last record is dropped.
            def load(lines):
                rows = []
                for line in lines:
                    if not line.strip():
                        continue
                    rows.append(line.strip())
                if rows:
                    rows.pop()
                return rows
            def report(lines):
                return len(load(lines))
            Fix only the bug. Return one python block defining load and report.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert load(["a", "b", ""]) == ["a", "b"]
            assert load(["a"]) == ["a"]
            assert report(["x", "y", "z"]) == 3
            assert load([]) == []
        """),
    },
    {
        "name": "state-machine",
        "prompt": textwrap.dedent("""
            A lock starts closed. Commands: open, close, pass.
            pass is allowed only when open, and then the lock closes.
            open when already open is an error. close when already closed is an error.
            Write run(commands) -> (accepted_passes, error_or_None).
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert run(["open", "pass"]) == (1, None)
            assert run(["pass"]) == (0, "closed")
            assert run(["open", "open"]) == (0, "already-open")
            assert run(["open", "pass", "pass"]) == (1, "closed")
            assert run(["close"]) == (0, "already-closed")
        """),
    },
    {
        "name": "edit-distance",
        "prompt": textwrap.dedent("""
            Write edit_distance(a, b), the Levenshtein distance with insert, delete, and substitute costing 1.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert edit_distance("kitten", "sitting") == 3
            assert edit_distance("", "abc") == 3
            assert edit_distance("abc", "abc") == 0
            assert edit_distance("a", "b") == 1
        """),
    },
    {
        "name": "tool-plan",
        "prompt": textwrap.dedent("""
            Reply with only a JSON array of exactly two objects, no markdown.
            First: {"name":"read_file","arguments":{"path":"src/kv.py","start":120,"end":160}}
            Second: {"name":"replace","arguments":{"path":"src/kv.py","old":"pop()","new":"pop(0)"}}
        """).strip(),
        "check": "json-exact",
        "expect": [
            {"name": "read_file", "arguments": {"path": "src/kv.py", "start": 120, "end": 160}},
            {"name": "replace", "arguments": {"path": "src/kv.py", "old": "pop()", "new": "pop(0)"}},
        ],
    },
    {
        "name": "graph-distance",
        "prompt": textwrap.dedent("""
            Write shortest(edges, src, dst). edges is a list of (u, v, w) undirected positive weights.
            Return the distance, or -1 if unreachable.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            edges = [("a", "b", 1), ("b", "c", 2), ("a", "c", 10)]
            assert shortest(edges, "a", "c") == 3
            assert shortest(edges, "a", "a") == 0
            assert shortest(edges, "a", "z") == -1
        """),
    },
    {
        "name": "js-group",
        "prompt": textwrap.dedent("""
            Write JavaScript function totals(rows) where rows are {sku, cents}.
            Return an object mapping sku to summed cents.
            End the file with exactly:
            const got = totals([{sku:'a', cents:10},{sku:'b', cents:5},{sku:'a', cents:7}]);
            if (got.a !== 17 || got.b !== 5) throw new Error('bad');
            Return one javascript block.
        """).strip(),
        "check": "node",
    },
    {
        "name": "go-median",
        "prompt": textwrap.dedent("""
            Write a complete Go program. Median(nums []int) int returns the lower middle
            of the sorted values. For an even count, return the lower of the two middle values.
            main must be exactly:
            func main() {
                if Median([]int{3, 1, 2}) != 2 { panic("odd") }
                if Median([]int{1, 2, 3, 4}) != 2 { panic("even") }
                if Median([]int{9}) != 9 { panic("one") }
            }
            Return one go block.
        """).strip(),
        "check": "go",
    },
    {
        "name": "invoice-cents",
        "prompt": textwrap.dedent("""
            Items: apple qty 3 at 250 cents, tax 5%. pear qty 1 at 1000 cents, tax 0%.
            Compute tax as floor(cents * percent / 100). A 100-cent coupon applies after tax and cannot make the total negative.
            Reply with only JSON {"due": <integer cents>}.
        """).strip(),
        "check": "json-field",
        "field": "due",
        "expect": 1687,
    },
]


def main() -> None:
    import sys
    from datetime import datetime, timezone
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--thinking", default="server-default")
    parser.add_argument("--engine", default="vllm")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    passed = 0
    skipped = 0
    total_tokens = 0
    reasoning_tokens = 0
    total_time = 0.0
    rows = []
    for task in TASKS:
        print(f"TASK {args.tag} {task['name']}", flush=True)
        try:
            result = chat(args.base_url.rstrip("/"), args.model, task["prompt"], args.max_tokens, args.thinking)
            if task["check"] == "json-exact":
                obj = extract_json(result["text"])
                ok, detail = obj == task["expect"], json.dumps(obj)[:300]
            else:
                ok, detail = check(task, result["text"])
            err = None
        except Exception as exc:  # noqa: BLE001
            result = {"usage": {}, "elapsed_s": 0.0, "text": ""}
            ok, detail, err = False, "", f"{type(exc).__name__}: {exc}"
        if detail in {"node-missing", "go-missing"}:
            skipped += 1
        else:
            passed += int(ok)
        usage = result.get("usage") or {}
        tokens = int(usage.get("completion_tokens") or 0)
        details = usage.get("completion_tokens_details") or {}
        reasoning_tokens += int(details.get("reasoning_tokens") or 0)
        elapsed = float(result.get("elapsed_s") or 0)
        total_tokens += tokens
        total_time += elapsed
        print(f"  ok={ok} tokens={tokens} reasoning={details.get('reasoning_tokens')} elapsed={elapsed:.1f} {str(detail)[:140]}", flush=True)
        rows.append({"name": task["name"], "ok": bool(ok) and detail not in {"node-missing", "go-missing"}, "detail": str(detail)[:500], "error": err, "usage": usage, "elapsed_s": elapsed, "text": str(result.get("text") or "")[:4000]})
        (ROOT / "raw" / f"quality4-{args.tag}-{task['name']}.json").write_text(json.dumps(rows[-1])[:80000], encoding="utf-8")
    attempted = len(TASKS) - skipped
    record({
        "experiment_id": f"quality4-{args.tag}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
        "model": args.model,
        "hf_id": args.model,
        "quantization": "NVFP4" if "35B" in args.model or "Qwen3.6" in args.model else "Q4_K_M",
        "engine": args.engine,
        "engine_version": args.engine,
        "profile": "quality-hard-10",
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
            "reasoning_tokens": reasoning_tokens,
            "tasks_per_minute": (passed / total_time * 60) if total_time else None,
            "tasks": [row["name"] + ":" + str(row["ok"]) for row in rows],
        }),
    })
    print(f"QUALITY {args.tag} {passed}/{attempted} skipped={skipped} minutes={total_time/60:.2f}", flush=True)


if __name__ == "__main__":
    main()
