"""Render the actual checker reports as a browser-based structural model viewer."""

import argparse
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from check import HERE, check


def render():
    reports = {name: check(HERE / "fixtures" / name) for name in ("valid", "invalid")}
    payload = {"reports": reports,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    # Keep source strings inside the data block, even if they contain </script>.
    data = json.dumps(payload).replace("<", "\\u003c")
    return (HERE / "viewer.html").read_text().replace("__MODEL_DATA__", data)


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        try:
            page = render()
            status = 200
        except Exception as error:
            page = ("<!doctype html><title>Model check failed</title>"
                    "<h1>Model check failed</h1><pre>" + escape(str(error)) + "</pre>")
            status = 500
        content = page.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Refresh reports on each page load")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path, default=HERE / "structure.html",
                        help="Snapshot HTML path when not serving")
    args = parser.parse_args()
    if args.serve:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), ViewerHandler)
        print(f"Structural viewer: http://127.0.0.1:{server.server_port}", flush=True)
        print("Reload the page to re-extract imports and evaluate OCL. Ctrl-C stops the viewer.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    else:
        args.output.write_text(render())
        print(f"Open {args.output.resolve()} in a browser.")


if __name__ == "__main__":
    main()
