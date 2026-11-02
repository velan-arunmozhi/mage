#!/usr/bin/env python3
"""Multi-turn auto tool calls, streamed and not, looking for Harmony name leaks."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/")
TURNS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
OUT = sys.argv[3] if len(sys.argv) > 3 else ""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"filePath": {"type": "string"}},
                "required": ["filePath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]
STEPS = [
    ("read", "Read the file /app/README.md with the read tool."),
    ("grep", "Search for the word version in /app/README.md with the grep tool."),
    ("bash", "Run the command pwd with the bash tool."),
    ("read", "Read /app/setup.py with the read tool."),
    ("grep", "Search for def in /app/setup.py with the grep tool."),
    ("bash", "Run the command ls /app with the bash tool."),
]


def post(body: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def parse_stream(raw: bytes) -> tuple[str, str]:
    name = ""
    arguments = ""
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            event = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        delta = (event.get("choices") or [{}])[0].get("delta") or {}
        for call in delta.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name"):
                name += fn["name"]
            if fn.get("arguments"):
                arguments += fn["arguments"]
    return name, arguments


def one(messages: list[dict], stream: bool) -> dict:
    body = {
        "model": "gpt-oss-20b",
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 128,
        "temperature": 0,
        "stream": stream,
    }
    code, raw = post(body)
    if code != 200:
        return {"error": f"HTTP {code}: {raw.decode('utf-8', 'replace')[:300]}"}
    if stream:
        name, arguments = parse_stream(raw)
        return {"name": name, "arguments": arguments[:200]}
    data = json.loads(raw.decode())
    message = data["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        return {"name": "", "arguments": "", "content": (message.get("content") or "")[:160]}
    return {
        "name": calls[0]["function"]["name"],
        "arguments": (calls[0]["function"].get("arguments") or "")[:200],
        "call_id": calls[0].get("id") or "",
    }


def run_mode(stream: bool) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": "Reasoning: medium"},
        {
            "role": "user",
            "content": "Use one tool per reply. Do not answer in prose.",
        },
    ]
    rows = []
    for turn in range(TURNS):
        expected, instruction = STEPS[turn % len(STEPS)]
        messages.append({"role": "user", "content": instruction})
        row = one(messages, stream)
        row["turn"] = turn
        row["expected"] = expected
        row["stream"] = stream
        name = row.get("name") or ""
        row["clean"] = name == expected
        row["leaked"] = "<|" in name
        rows.append(row)
        print(
            f"{'stream' if stream else 'plain'} turn {turn} name={name!r} leaked={row['leaked']}",
            flush=True,
        )
        if "error" in row:
            break
        call_id = row.get("call_id") or f"call-{int(stream)}-{turn}"
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": expected,
                            "arguments": row.get("arguments") or "{}",
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "ok",
            }
        )
    return rows


def main() -> None:
    rows = run_mode(False) + run_mode(True)
    summary = {
        "turns": len(rows),
        "clean": sum(1 for row in rows if row.get("clean")),
        "malformed": sum(1 for row in rows if row.get("name") and not row.get("clean")),
        "leaked": sum(1 for row in rows if row.get("leaked")),
        "errors": sum(1 for row in rows if "error" in row),
        "rows": rows,
    }
    text = json.dumps(summary, indent=2)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
