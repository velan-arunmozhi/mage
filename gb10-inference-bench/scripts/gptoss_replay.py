#!/usr/bin/env python3
"""Replay a Harbor tool prefix and record the next streamed tool name."""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/")
PREFIX = json.load(open(sys.argv[2], encoding="utf-8"))
TURNS = int(sys.argv[3]) if len(sys.argv) > 3 else 8

TOOLS = [
    {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}
    for name in ("bash", "read", "grep", "glob", "edit", "search")
]


def stream_names(messages: list[dict]) -> list[str]:
    body = {
        "model": "gpt-oss-20b",
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 128,
        "temperature": 0,
        "stream": True,
    }
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    names: dict[int, str] = {}
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            delta = (event.get("choices") or [{}])[0].get("delta") or {}
            for call in delta.get("tool_calls") or []:
                idx = call.get("index", 0)
                fn = (call.get("function") or {}).get("name")
                if fn:
                    names[idx] = names.get(idx, "") + fn
    return [names[k] for k in sorted(names)]


def main() -> None:
    messages = list(PREFIX)
    leaked = 0
    for turn in range(TURNS):
        messages.append({"role": "user", "content": "Search the repository for the function that builds the version string. Use one tool."})
        found = stream_names(messages)
        bad = [name for name in found if "<|" in name]
        leaked += len(bad)
        print(f"turn {turn} names={found!r}", flush=True)
        name = found[0] if found else "grep"
        clean = name.split("<|", 1)[0] or "grep"
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"r{turn}",
                "type": "function",
                "function": {"name": clean, "arguments": "{\"q\": \"version\"}"},
            }],
        })
        messages.append({"role": "tool", "tool_call_id": f"r{turn}", "content": "no matches"})
    print(json.dumps({"turns": TURNS, "leaked": leaked}))


if __name__ == "__main__":
    main()
