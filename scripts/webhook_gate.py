"""Webhook-only gate for a public tunnel: forwards /webhooks/whatsapp to the console and nothing else.

The tunnel points here (default 127.0.0.1:8001), never at the console, so the login page, chat, negotiations and
supplier API cannot be reached from the internet even if the console has a bug. The gate checks Meta's verify token
and HMAC signature itself, so a forged or unsigned call is dropped here and never reaches the console, which checks
both again. It reads WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN from the environment or ../.env and will not start
without them.

    python3 scripts/webhook_gate.py [--port 8001] [--upstream http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

PATH = "/webhooks/whatsapp"
MAX_BODY = 1 << 20  # Meta batches are small; refuse anything larger without reading it
PASS_HEADERS = ("content-type", "x-hub-signature-256")
RATE_PER_MIN = 120  # all requests through the tunnel; Meta sends a few per message, a flood gets 429
ENV = Path(__file__).resolve().parents[1] / ".env"


def env_val(key: str, env: Path = ENV) -> str:
    if os.environ.get(key):
        return os.environ[key]
    try:
        lines = env.read_text().splitlines()
    except OSError:
        return ""
    vals = [l.split("=", 1)[1].split(" #", 1)[0].strip().strip("'\"") for l in lines if l.startswith(key + "=")]
    return vals[-1] if vals else ""


class Window:
    """Requests in the last minute, across every caller."""

    def __init__(self, limit: int = RATE_PER_MIN, clock=time.monotonic):
        self.limit, self.clock, self.hits, self.lock = limit, clock, [], threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            now = self.clock()
            self.hits = [t for t in self.hits if now - t < 60]
            if len(self.hits) >= self.limit:
                return False
            self.hits.append(now)
            return True


class Gate(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8000"
    app_secret = b""
    verify_token = ""
    window = Window()
    timeout = 10  # a client that trickles its request is dropped
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

    def _admit(self) -> bool:
        if not self.window.allow():
            self._send(429, b"slow down")
            return False
        if urlsplit(self.path).path != PATH:
            self._send(404, b"not found")
            return False
        return True

    def _forward(self, body: bytes | None, target: str) -> None:
        headers = {k: v for k in PASS_HEADERS if (v := self.headers.get(k))}
        req = urllib.request.Request(self.upstream + target, body, headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self._send(r.status, r.read(), r.headers.get("content-type", "text/plain"))
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read()[:2000], e.headers.get("content-type", "text/plain"))
        except OSError:
            self._send(502, b"console not reachable")

    def do_GET(self):  # Meta's subscription check: only a request carrying our verify token gets through
        if not self._admit():
            return
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        challenge = q.get("hub.challenge", "")
        if not (q.get("hub.mode") == "subscribe" and challenge.isdigit() and len(challenge) <= 64
                and hmac.compare_digest(q.get("hub.verify_token", "").encode(), self.verify_token.encode())):
            return self._send(403, b"forbidden")
        self._forward(None, PATH + "?" + urlencode({k: q[k] for k in ("hub.mode", "hub.verify_token", "hub.challenge")}))

    def do_POST(self):  # message events: only a body Meta signed with the app secret gets through
        if not self._admit():
            return
        try:
            n = int(self.headers.get("content-length") or 0)
        except ValueError:
            return self._send(400, b"bad length")
        if n > MAX_BODY:
            return self._send(413, b"too large")
        body = self.rfile.read(n)
        sig = self.headers.get("x-hub-signature-256", "")
        want = "sha256=" + hmac.new(self.app_secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig.encode(), want.encode()):
            return self._send(401, b"bad signature")
        if not (self.headers.get("content-type") or "").startswith("application/json"):
            return self._send(415, b"json only")
        self._forward(body, PATH)

    def _refuse(self):
        self._send(405, b"method not allowed")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _refuse


def serve(port: int, upstream: str, app_secret: str, verify_token: str,
          window: Window | None = None) -> ThreadingHTTPServer:
    if not app_secret or not verify_token:
        raise ValueError("WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN are required")
    Gate.upstream, Gate.app_secret, Gate.verify_token = upstream.rstrip("/"), app_secret.encode(), verify_token
    Gate.window = window or Window()
    return ThreadingHTTPServer(("127.0.0.1", port), Gate)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--upstream", default="http://127.0.0.1:8000")
    a = ap.parse_args(argv)
    try:
        srv = serve(a.port, a.upstream, env_val("WHATSAPP_APP_SECRET"), env_val("WHATSAPP_VERIFY_TOKEN"))
    except ValueError as e:
        print(f"webhook gate not started: {e} (environment or .env)", flush=True)
        return 1
    print(f"webhook gate on 127.0.0.1:{a.port}: only {PATH} with Meta's verify token or signature is forwarded "
          f"to {a.upstream}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
