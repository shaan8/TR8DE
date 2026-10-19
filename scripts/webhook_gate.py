"""Webhook-only gate for a public tunnel: forwards /webhooks/whatsapp to the console and nothing else.

The tunnel points here (default 127.0.0.1:8001), never at the console, so the login page, chat, negotiations and
supplier API cannot be reached from the internet even if the console has a bug. Meta's signature is still checked by
the console; this gate only narrows what can arrive.

    python3 scripts/webhook_gate.py [--port 8001] [--upstream http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PATH = "/webhooks/whatsapp"
MAX_BODY = 1 << 20  # Meta batches are small; refuse anything larger without reading it
PASS_HEADERS = ("content-type", "x-hub-signature-256")


class Gate(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8000"
    server_version = "tiwala-webhook-gate"
    sys_version = ""

    def log_message(self, fmt, *args):  # one line per request, no bodies or query strings (they carry the token)
        pass

    def _note(self, code: int) -> None:
        print(f"{time.strftime('%H:%M:%S')} {self.command} {urlsplit(self.path).path[:60]} -> {code}", flush=True)

    def _send(self, code: int, body: bytes, ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self._note(code)

    def _forward(self, body: bytes | None) -> None:
        if urlsplit(self.path).path != PATH:
            return self._send(404, b"not found")
        headers = {k: v for k in PASS_HEADERS if (v := self.headers.get(k))}
        req = urllib.request.Request(self.upstream + self.path, body, headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self._send(r.status, r.read(), r.headers.get("content-type", "text/plain"))
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read()[:2000], e.headers.get("content-type", "text/plain"))
        except OSError:
            self._send(502, b"console not reachable")

    def do_GET(self):  # Meta's subscription check
        self._forward(None)

    def do_POST(self):
        try:
            n = int(self.headers.get("content-length") or 0)
        except ValueError:
            return self._send(400, b"bad length")
        if n > MAX_BODY:
            return self._send(413, b"too large")
        self._forward(self.rfile.read(n))

    def _refuse(self):
        self._send(405, b"method not allowed")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse


def serve(port: int, upstream: str) -> ThreadingHTTPServer:
    Gate.upstream = upstream.rstrip("/")
    return ThreadingHTTPServer(("127.0.0.1", port), Gate)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--upstream", default="http://127.0.0.1:8000")
    a = ap.parse_args(argv)
    srv = serve(a.port, a.upstream)
    print(f"webhook gate on 127.0.0.1:{a.port}: only {PATH} is forwarded to {a.upstream}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
