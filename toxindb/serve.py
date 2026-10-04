"""Minimal HTTP server for toxindb (offline-first, read-only)."""
from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from .api import analyze_trace


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default logging
        return

    def _set_headers(self, status: int = 200, ct: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-type", ct)
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "ok"}).encode())
            return
        self._set_headers(404)
        self.wfile.write(json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        if self.path != "/analyze":
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "not found"}).encode())
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": f"invalid json: {e}"}).encode())
            return
        try:
            if "trace_path" in data:
                res = analyze_trace(data["trace_path"])
                out = {
                    "alert_count": res.alert_count,
                    "alerts": [a.to_dict() for a in res.alerts],
                }
                self._set_headers(200)
                self.wfile.write(json.dumps(out).encode())
                return
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "provide trace_path"}).encode())
        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())


def serve(host: str = "127.0.0.1", port: int = 0) -> None:
    httpd = HTTPServer((host, port), _Handler)
    httpd.serve_forever()
