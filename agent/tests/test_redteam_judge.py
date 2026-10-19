"""Regressions for the judge-style review of 19 October 2026 (SECURITY.md, "Judge walkthrough")."""
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from console import negotiation_api as napi
from console import server
from tiwala_agent.core import OfflineLLM, Tiwala
from tiwala_agent.whatsapp import RATE_N, Contact, Inbound

from .test_negotiation import LUMEN, T0, gateway, open_wa, world  # noqa: F401  (world is a fixture)


def test_owner_turns_are_serialized():
    """J1: two requests at once could both read the same pending confirmation; every entry point takes one lock."""
    t = Tiwala.__new__(Tiwala)
    t.turn_lock = threading.RLock()
    inside, overlap = [], []

    def slow(text):
        overlap.append(len(inside))
        inside.append(text)
        time.sleep(0.05)
        inside.remove(text)
        return text
    t._handle = slow
    t._tick = lambda: slow("tick") and []
    ths = [threading.Thread(target=t.handle, args=("yes",)) for _ in range(4)] + [threading.Thread(target=t.tick)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    assert len(overlap) == 5 and max(overlap) == 0


def test_oversized_bodies_are_refused_before_parsing():
    """J2: public endpoints (login, webhook, supplier API) read whole bodies; cap them."""
    c = TestClient(server.app)
    big = b"{" + b" " * (300 * 1024) + b"}"
    for path in ("/api/login", "/webhooks/whatsapp", "/api/supplier/mandate?supplier=0x0"):
        assert c.post(path, content=big, headers={"Content-Type": "application/json"}).status_code == 413
    assert c.post("/api/login", content=b"{}", headers={"Content-Length": "abc"}).status_code in (400, 413)


def _req(headers: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(k.lower().encode(), v.encode())
                                                                               for k, v in headers.items()]})


def test_supplier_page_token_travels_in_a_header_not_the_url(monkeypatch):
    """J3: the supplier link carried its token in the query string (history, logs, screenshots); now #fragment."""
    seen = []
    monkeypatch.setattr(napi, "svc", lambda: type("S", (), {"mark_api_seen": lambda self, a: seen.append(a)})())
    tok = napi.supplier_token(LUMEN)
    napi._auth(LUMEN, "", _req({"X-Supplier-Token": tok}))  # web page: accepted, not counted as an API client
    assert seen == []
    napi._auth(LUMEN, "", _req({"Authorization": f"Bearer {tok}"}))
    assert seen == [LUMEN]
    with pytest.raises(Exception):
        napi._auth(LUMEN, "", _req({"X-Supplier-Token": tok[:-1] + ("0" if tok[-1] != "0" else "1")}))
    src = open(napi.__file__).read()
    assert "&token={supplier_token" not in src and "#token={supplier_token" in src


def test_chat_flood_from_a_bound_sender_is_capped(world):  # noqa: F811
    """J4: a bound WhatsApp or Telegram chat could send unlimited messages, each one a model call."""
    g, esc = gateway(world)
    g.contacts.put(Contact(LUMEN, f"sim:{LUMEN.lower()}", "simulator", opted_in_at=T0 - 10))
    open_wa(world)
    out = [g.handle(Inbound(f"f{i}", f"sim:{LUMEN.lower()}", T0, "maybe 120 each?"), "simulator")["status"]
           for i in range(RATE_N + 5)]
    assert "rate_limited" not in out[:RATE_N] and set(out[RATE_N:]) == {"rate_limited"}
    assert sum("more than" in e for e in esc) == 1
    world["clock"].t += 601
    assert g.handle(Inbound("late", f"sim:{LUMEN.lower()}", T0 + 601, "ok"), "simulator")["status"] != "rate_limited"


def test_offline_message_names_every_provider():
    """J5: without a key the chat named only DEEPSEEK_API_KEY, so a judge with a Qwen key looked in the wrong place."""
    with pytest.raises(Exception) as e:
        OfflineLLM("DEEPSEEK_API_KEY").complete("", [])
    assert all(k in str(e.value) for k in ("DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
                                           "ANTHROPIC_API_KEY"))


def test_password_file_is_owner_only_and_deploy_reads_env_without_running_it(tmp_path):
    """J8: set-password could create .env world-readable; the deploy script ran .env as shell code, so a
    double-quoted scrypt hash ("$3...") or a value with spaces aborted the deployment."""
    import os
    import subprocess
    from pathlib import Path

    from console.auth import write_env
    env = tmp_path / ".env"
    write_env({"TIWALA_ADMIN_PASS_HASH": "scrypt$32768$8$1$abc$def"}, env)
    assert oct(env.stat().st_mode & 0o777) == "0o600"
    env.write_text('PRIVATE_KEY=0xabc\nTIWALA_ADMIN_PASS_HASH="scrypt$32768$8$1$x$y"\nNOTE=two words here\n'
                   "OWNER_PRIVATE_KEY='0xdef'  # owner\n")
    script = Path(__file__).parents[2] / "scripts" / "deploy-sepolia.sh"
    loader = script.read_text().split("set -euo pipefail\n", 1)[1].split("\n: ", 1)[0]
    out = subprocess.run(["bash", "-c", "set -euo pipefail\n" + loader + '\necho "$PRIVATE_KEY $OWNER_PRIVATE_KEY"'],
                         cwd=tmp_path, capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert out.returncode == 0 and out.stdout.strip() == "0xabc 0xdef", "the .env loader failed"
