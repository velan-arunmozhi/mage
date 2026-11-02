#!/usr/bin/env python3
"""Forward chat completions to vLLM and attach the requested reasoning mode."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request

UPSTREAM = os.environ.get("PROXY_UPSTREAM", "http://127.0.0.1:18080").rstrip("/")
MODE = os.environ.get("PROXY_MODE", "qwen-off")
LOG = os.environ.get("PROXY_LOG", "")


def _insert_reasoning(messages: list, effort: str) -> list:
    if not any(
        isinstance(item, dict)
        and item.get("role") == "system"
        and "Reasoning:" in str(item.get("content") or "")
        for item in messages
    ):
        messages.insert(0, {"role": "system", "content": f"Reasoning: {effort}"})
    return messages


def adjust(body: dict) -> dict:
    if MODE == "qwen-off":
        body["chat_template_kwargs"] = {"enable_thinking": False}
        # Responses API requests still honor the chat template when this is set.
        reasoning = body.get("reasoning")
        if isinstance(reasoning, dict):
            reasoning["effort"] = "none"
            body["reasoning"] = reasoning
    elif MODE in {"gpt-low", "gpt-medium"}:
        effort = "low" if MODE == "gpt-low" else "medium"
        if isinstance(body.get("messages"), list):
            body["messages"] = _insert_reasoning(list(body["messages"]), effort)
        if isinstance(body.get("input"), list):
            body["input"] = _insert_reasoning(list(body["input"]), effort)
        body["reasoning"] = {"effort": effort}
    return body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path
        data = raw
        streaming = False
        if path.startswith("/v1/chat/completions") and raw:
            try:
                body = json.loads(raw.decode())
            except json.JSONDecodeError:
                body = None
            if isinstance(body, dict):
                streaming = bool(body.get("stream"))
                data = json.dumps(adjust(body)).encode()
        req = urllib.request.Request(
            UPSTREAM + path,
            data=data if self.command != "GET" else None,
            method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            resp = urllib.request.urlopen(req, timeout=3600)
            code = resp.status
            ctype = resp.headers.get("Content-Type", "application/json")
            error_body = None
        except urllib.error.HTTPError as exc:
            resp = None
            error_body = exc.read()
            code = exc.code
            ctype = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if error_body is not None or not streaming:
            payload = error_body if error_body is not None else resp.read()
            if LOG and path.startswith("/v1/chat/completions") and error_body is None:
                try:
                    parsed = json.loads(payload.decode())
                    with open(LOG, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"mode": MODE, "usage": parsed.get("usage") or {}, "status": code}) + "\n")
                except Exception:
                    pass
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            if resp is not None:
                resp.close()
            return
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        assert resp is not None
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(f"{len(chunk):X}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        finally:
            self.wfile.write(b"0\r\n\r\n")
            resp.close()

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s\n" % (fmt % args))


def main() -> None:
    port = int(sys.argv[1] if len(sys.argv) > 1 else "18081")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"PROXY {MODE} -> {UPSTREAM} on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
