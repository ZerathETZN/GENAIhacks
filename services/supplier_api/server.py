"""Tiny synthetic supplier portal (AGENTS.md §4, source 4). Zetaris reads it as the
Lightning REST table supplier_rest.deliveries. Standard library only.

  GET /deliveries  -> JSON array of SYNTHETIC deliveries
  GET /health      -> {"status": "ok"}
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA = Path(os.getenv("SUPPLIER_DATA", "/data/sample/supplier/deliveries.json"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/deliveries":
            self._send(200, DATA.read_bytes())  # re-read each time, so regenerating data needs no restart
        elif path == "/health":
            self._send(200, b'{"status": "ok"}')
        else:
            self._send(404, b'{"error": "not found"}')


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"supplier api on :{port}, serving {DATA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
