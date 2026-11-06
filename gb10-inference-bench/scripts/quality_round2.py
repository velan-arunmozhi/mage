#!/usr/bin/env python3
"""Checked coding tasks. Python solutions are executed. JSON is parsed."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import record

ROOT = Path("/scratch/scholar/billin19/gb10-inference-bench")
BASE = "http://127.0.0.1:8000"
MODEL = "nvidia/Qwen3.6-35B-A3B-NVFP4"


def chat(prompt: str, max_tokens: int) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.perf_counter() - started
    message = (data.get("choices") or [{}])[0].get("message") or {}
    text = "\n".join(
        str(message.get(key) or "")
        for key in ("content", "reasoning", "reasoning_content")
    )
    return {"text": text, "usage": data.get("usage") or {}, "elapsed_s": elapsed, "message": message}


def code_block(text: str, lang: str) -> str:
    matches = re.findall(rf"```{lang}\s*(.*?)```", text, flags=re.I | re.S)
    if matches:
        return matches[-1]
    matches = re.findall(r"```\s*(.*?)```", text, flags=re.S)
    return matches[-1] if matches else text


def run_python(code: str, tests: str) -> tuple[bool, str]:
    program = textwrap.dedent(code).lstrip() + "\n" + textwrap.dedent(tests)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sol.py"
        path.write_text(program, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True,
                text=True,
                timeout=8,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        out = (proc.stdout + proc.stderr)[-800:]
        return proc.returncode == 0, out


def run_node(code: str) -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:
        return False, "node-missing"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sol.js"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=8, cwd=tmp)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]


def run_go(code: str) -> tuple[bool, str]:
    go = shutil.which("go")
    if not go:
        return False, "go-missing"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.go"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run([go, "run", str(path)], capture_output=True, text=True, timeout=40, cwd=tmp)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]


TASKS = [
    {
        "name": "py-even-sum",
        "prompt": textwrap.dedent("""
            Fix the Python function so even_sum(n) is the sum of even integers from 1 through n inclusive.
            Return only a python code block defining even_sum.
            Current code:
            def even_sum(n):
                total = 0
                for i in range(1, n):
                    if i % 2 == 0:
                        total += i
                return total
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert even_sum(10) == 30
            assert even_sum(1) == 0
            assert even_sum(7) == 12
            assert even_sum(8) == 20
        """),
    },
    {
        "name": "py-binary-search",
        "prompt": textwrap.dedent("""
            Fix binary_search so it returns the index of target in a sorted list, or -1 if absent.
            Return only a python code block defining binary_search.
            Current code:
            def binary_search(nums, target):
                lo, hi = 0, len(nums)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if nums[mid] < target:
                        lo = mid
                    else:
                        hi = mid
                return lo
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert binary_search([1, 3, 5, 7], 5) == 2
            assert binary_search([1, 3, 5, 7], 1) == 0
            assert binary_search([1, 3, 5, 7], 7) == 3
            assert binary_search([1, 3, 5, 7], 4) == -1
            assert binary_search([], 1) == -1
        """),
    },
    {
        "name": "py-parse-pairs",
        "prompt": textwrap.dedent("""
            Write parse_pairs(text) that reads lines of 'key=value' and returns a dict.
            Ignore blank lines and lines starting with '#'.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert parse_pairs("a=1\\nb=two\\n\\n#c=3\\n") == {"a": "1", "b": "two"}
            assert parse_pairs("") == {}
            assert parse_pairs("# only\\n") == {}
        """),
    },
    {
        "name": "py-debug-print",
        "prompt": textwrap.dedent("""
            How many times does this print 'tick'?
            i = 0
            while i < 5:
                if i % 2 == 0:
                    print('tick')
                i += 1
            Reply with a JSON object {"ticks": <integer>} and nothing else in the final answer.
        """).strip(),
        "check": "json-field",
        "field": "ticks",
        "expect": 3,
    },
    {
        "name": "tool-json",
        "prompt": textwrap.dedent("""
            Call the tool read_file on path src/app.py with line 40.
            Reply with only a JSON object of the form
            {"name":"read_file","arguments":{"path":"src/app.py","line":40}}
        """).strip(),
        "check": "tool",
    },
    {
        "name": "py-two-bugs",
        "prompt": textwrap.dedent("""
            Fix both bugs. clamp(x, lo, hi) returns x limited to [lo, hi].
            mean(xs) returns the arithmetic mean of a non-empty list.
            Return only a python code block defining both functions.
            Current code:
            def clamp(x, lo, hi):
                if x < lo:
                    return hi
                if x > hi:
                    return lo
                return x
            def mean(xs):
                return sum(xs) / (len(xs) - 1)
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert clamp(5, 0, 3) == 3
            assert clamp(-1, 0, 3) == 0
            assert clamp(2, 0, 3) == 2
            assert mean([2, 4, 6]) == 4
            assert mean([10]) == 10
        """),
    },
    {
        "name": "ts-sum",
        "prompt": textwrap.dedent("""
            Write a JavaScript function sumEven(nums) that returns the sum of even numbers.
            Include this exact test at the bottom and do not change it:
            if (sumEven([1,2,3,4,5,6]) !== 12) throw new Error('bad')
            if (sumEven([1]) !== 0) throw new Error('bad0')
            Return only one javascript code block.
        """).strip(),
        "check": "node",
    },
    {
        "name": "go-sum",
        "prompt": textwrap.dedent("""
            Write a complete Go program in package main. Function SumEven(nums []int) int
            returns the sum of even numbers. main must print nothing extra.
            Include this main exactly:
            func main() {
                if SumEven([]int{1, 2, 3, 4}) != 6 { panic("bad") }
                if SumEven([]int{1}) != 0 { panic("bad0") }
            }
            Return only one go code block.
        """).strip(),
        "check": "go",
    },
    {
        "name": "py-nested-update",
        "prompt": textwrap.dedent("""
            Write apply_updates(state, updates). state is a dict. updates is a list of
            pairs [key, value]. Return a new dict and do not mutate the input.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            src = {"a": 1}
            out = apply_updates(src, [["b", 2], ["a", 3]])
            assert out == {"a": 3, "b": 2}
            assert src == {"a": 1}
            assert apply_updates({}, []) == {}
        """),
    },
    {
        "name": "logic-steps",
        "prompt": textwrap.dedent("""
            A list starts as [1, 2, 3]. Then: append 4, reverse it, drop the first item, append 0.
            Reply with only JSON {"result": [..]} using the final list.
        """).strip(),
        "check": "json-field",
        "field": "result",
        "expect": [3, 2, 1, 0],
    },
    {
        "name": "py-retry-count",
        "prompt": textwrap.dedent("""
            Write attempts_until_ok(results) where results is a list of booleans.
            Return the 1-based index of the first True, or 0 if none are True.
            Return only a python code block.
        """).strip(),
        "check": "python",
        "tests": textwrap.dedent("""
            assert attempts_until_ok([False, False, True]) == 3
            assert attempts_until_ok([True]) == 1
            assert attempts_until_ok([False, False]) == 0
            assert attempts_until_ok([]) == 0
        """),
    },
    {
        "name": "tool-multi",
        "prompt": textwrap.dedent("""
            Reply with only a JSON array of two tool calls, in order:
            first write_file path notes.txt content hello,
            then run_tests path notes.txt.
            Each object has name and arguments.
        """).strip(),
        "check": "tool-array",
    },
]


def extract_json(text: str):
    decoder = json.JSONDecoder()
    found = None
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        found = obj
    if found is None:
        raise ValueError("no json")
    return found


def check(task: dict, text: str) -> tuple[bool, str]:
    kind = task["check"]
    if kind == "python":
        return run_python(code_block(text, "python"), task["tests"])
    if kind == "node":
        return run_node(code_block(text, "javascript"))
    if kind == "go":
        return run_go(code_block(text, "go"))
    if kind == "json-field":
        try:
            obj = extract_json(text)
        except Exception as exc:
            return False, str(exc)
        return obj.get(task["field"]) == task["expect"], json.dumps(obj)[:400]
    if kind == "tool":
        try:
            obj = extract_json(text)
        except Exception as exc:
            return False, str(exc)
        ok = (
            isinstance(obj, dict)
            and obj.get("name") == "read_file"
            and isinstance(obj.get("arguments"), dict)
            and obj["arguments"].get("path") == "src/app.py"
            and obj["arguments"].get("line") == 40
        )
        return ok, json.dumps(obj)[:400]
    if kind == "tool-array":
        try:
            obj = extract_json(text)
        except Exception as exc:
            return False, str(exc)
        ok = (
            isinstance(obj, list)
            and len(obj) == 2
            and obj[0].get("name") == "write_file"
            and obj[0].get("arguments", {}).get("path") == "notes.txt"
            and obj[0].get("arguments", {}).get("content") == "hello"
            and obj[1].get("name") == "run_tests"
            and obj[1].get("arguments", {}).get("path") == "notes.txt"
        )
        return ok, json.dumps(obj)[:400]
    return False, "unknown"


def main() -> None:
    rows = []
    passed = 0
    for task in TASKS:
        print(f"TASK {task['name']}", flush=True)
        try:
            result = chat(task["prompt"], 3072)
            ok, detail = check(task, result["text"])
            err = None
        except Exception as exc:  # noqa: BLE001
            result = {"text": "", "usage": {}, "elapsed_s": None}
            ok, detail, err = False, "", f"{type(exc).__name__}: {exc}"
        passed += int(ok)
        usage = result.get("usage") or {}
        print(f"  ok={ok} tokens={usage.get('completion_tokens')} elapsed={result.get('elapsed_s')} detail={detail[:180]}", flush=True)
        row = {"name": task["name"], "ok": ok, "detail": detail, "error": err, "usage": usage, "elapsed_s": result.get("elapsed_s")}
        rows.append(row)
        (ROOT / "raw" / f"quality2-{task['name']}.json").write_text(json.dumps(row)[:80000], encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record({
        "experiment_id": f"qwen36-quality2-{stamp}",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
        "model": MODEL,
        "hf_id": MODEL,
        "quantization": "NVFP4",
        "engine": "vllm",
        "engine_version": "vllm 0.28.0 cuda-graphs mtp3",
        "profile": "quality-12",
        "context_configured": 131072,
        "concurrency_requested": 1,
        "mode": "quality",
        "mtp": "mtp3",
        "draft_tokens": 3,
        "completed": passed,
        "failed": len(TASKS) - passed,
        "notes": json.dumps({"passed": passed, "attempted": len(TASKS), "tasks": [r["name"] + ":" + str(r["ok"]) for r in rows]}),
    })
    print(f"QUALITY {passed}/{len(TASKS)}", flush=True)


if __name__ == "__main__":
    main()
