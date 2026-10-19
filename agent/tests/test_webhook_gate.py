"""The tunnel gate forwards only the WhatsApp webhook, only with Meta's token or signature, with only the headers
Meta's check needs."""
import hashlib
import hmac
import importlib.util
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("webhook_gate", Path(__file__).parents[2] / "scripts" / "webhook_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Upstream(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _ok(self, body=b""):
        Upstream.seen.append((self.command, self.path, dict(self.headers), body))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self._ok()

    def do_POST(self):
        self._ok(self.rfile.read(int(self.headers["content-length"])))


SECRET, TOKEN = "app-secret", "verify-me"
GET_OK = f"/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token={TOKEN}&hub.challenge=1"


def signed(body: bytes, secret: str = SECRET) -> dict:
    return {"Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


@pytest.fixture
def gw():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    g = gate.serve(0, f"http://127.0.0.1:{up.server_address[1]}", SECRET, TOKEN)
    for s in (up, g):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    Upstream.seen.clear()
    yield f"http://127.0.0.1:{g.server_address[1]}"
    up.shutdown(), g.shutdown()


def status(url, data=None, headers=None, method=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers or {}, method=method), timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_only_the_webhook_path_is_forwarded(gw):
    for path in ("/", "/api/session", "/api/login", "/api/supplier/x", "/webhooks/whatsapp/../api/chat",
                 "/webhooks/whatsappX", "/assets/index.js"):
        assert status(gw + path) == 404
    assert status(gw + "/api/login", b"{}", {"Content-Type": "application/json"}) == 404
    assert Upstream.seen == []


def test_webhook_get_and_signed_post_pass_through(gw):
    assert status(gw + GET_OK) == 200
    sig = signed(b'{"a":1}')
    assert status(gw + "/webhooks/whatsapp", b'{"a":1}', {**sig, "Cookie": "tiwala_session=x", "X-Tiwala": "1"}) == 200
    _, path, headers, body = Upstream.seen[-1]
    low = {k.lower(): v for k, v in headers.items()}
    assert path == "/webhooks/whatsapp" and body == b'{"a":1}' and low["x-hub-signature-256"] == sig["X-Hub-Signature-256"]
    assert "cookie" not in low and "x-tiwala" not in low  # a session cookie cannot ride through the tunnel


def test_other_methods_and_oversized_bodies_are_refused(gw):
    assert status(gw + "/webhooks/whatsapp", b"x", method="PUT") == 405
    big = b"x" * (gate.MAX_BODY + 1)
    try:  # refused before the body is read, so the client may see the 413 or a reset while still sending
        assert status(gw + "/webhooks/whatsapp", big, {"Content-Type": "application/json"}) == 413
    except urllib.error.URLError:
        pass
    assert Upstream.seen == []


def test_forged_calls_stop_at_the_gate(gw):
    body = b'{"entry":[]}'
    assert status(gw + "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=guess&hub.challenge=1") == 403
    assert status(gw + "/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=1") == 403
    assert status(gw + GET_OK.replace("challenge=1", "challenge=<script>")) == 403
    assert status(gw + "/webhooks/whatsapp", body, {"Content-Type": "application/json"}) == 401
    assert status(gw + "/webhooks/whatsapp", body, signed(body, "wrong-secret")) == 401
    assert status(gw + "/webhooks/whatsapp", body + b" ", signed(body)) == 401  # body changed after signing
    assert status(gw + "/webhooks/whatsapp", body, {**signed(body), "Content-Type": "text/plain"}) == 415
    assert Upstream.seen == []


def test_a_flood_is_rate_limited():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    g = gate.serve(0, f"http://127.0.0.1:{up.server_address[1]}", SECRET, TOKEN, gate.Window(limit=3))
    for s in (up, g):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{g.server_address[1]}"
    try:
        assert [status(url + GET_OK) for _ in range(5)] == [200, 200, 200, 429, 429]
    finally:
        up.shutdown(), g.shutdown()


def test_gate_will_not_start_without_meta_secrets():
    with pytest.raises(ValueError):
        gate.serve(0, "http://127.0.0.1:1", "", TOKEN)
    with pytest.raises(ValueError):
        gate.serve(0, "http://127.0.0.1:1", SECRET, "")
