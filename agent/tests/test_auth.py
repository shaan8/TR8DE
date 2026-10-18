"""Owner login in front of the console: scrypt hash, server-side sessions, lockout, CSRF, public paths."""
import pytest
from fastapi.testclient import TestClient

from console import auth as A
from console import server

ORIGIN = {"Origin": "http://testserver", "X-Tiwala": "1"}


@pytest.fixture
def client():
    a = server._auth()
    saved = (a.user, a.pass_hash, a.clock)
    t = [1_000_000.0]
    a.user, a.pass_hash, a.clock = "Shaan", A.hash_password("correct horse"), lambda: t[0]
    a.sessions.clear(), a.fails.clear()
    c = TestClient(server.app)
    c.t = t
    yield c
    a.user, a.pass_hash, a.clock = saved
    a.sessions.clear(), a.fails.clear()


def login(c, pw="correct horse", user="Shaan", headers=ORIGIN):
    return c.post("/api/login", json={"username": user, "password": pw}, headers=headers)


def test_hash_is_salted_scrypt_and_never_the_password():
    h1, h2 = A.hash_password("pw123456"), A.hash_password("pw123456")
    assert h1.startswith("scrypt$32768$8$1$") and h1 != h2 and "pw123456" not in h1
    assert A.check_password("pw123456", h1) and not A.check_password("pw123457", h1)


def test_everything_but_public_paths_needs_a_session(client):
    for path in ("/api/state", "/api/negotiations", "/api/verify", "/api/sim/supplier-link?supplier=0x1"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/message", json={"text": "hi"}, headers=ORIGIN).status_code == 401
    assert client.get("/api/session").json()["signed_in"] is False
    assert client.get("/docs").status_code in (401, 404) and client.get("/openapi.json").status_code in (401, 404)
    assert client.get("/api/supplier?supplier=0x1&token=bad").status_code != 401  # own token check
    assert client.get("/webhooks/whatsapp?hub.mode=subscribe").status_code == 403  # Meta's own check


def test_login_sets_a_strict_httponly_cookie_and_opens_the_api(client):
    assert login(client, "wrong").status_code == 401
    assert login(client, user="nobody").status_code == 401
    r = login(client, user="shaan")  # username is case-insensitive
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=43200" in cookie
    assert client.get("/api/session").json()["signed_in"] is True
    assert client.get("/api/fixtures").status_code == 200
    client.post("/api/logout", headers=ORIGIN)
    assert client.get("/api/fixtures").status_code == 401


def test_cross_site_and_headerless_posts_are_refused(client):
    assert login(client, headers={"X-Tiwala": "1", "Origin": "https://evil.example"}).status_code == 403
    assert login(client, headers={"Origin": "http://testserver"}).status_code == 403
    assert login(client).status_code == 200
    assert client.post("/api/tick", headers={"Origin": "https://evil.example", "X-Tiwala": "1"}).status_code == 403
    assert client.post("/api/tick", headers={"Origin": "http://testserver"}).status_code == 403


def test_lockout_after_repeated_failures_even_with_the_right_password(client):
    for _ in range(A.CLIENT_FAILS):
        assert login(client, "guess").status_code == 401
    assert login(client).status_code == 429
    client.t[0] += A.CLIENT_WINDOW_S + 1
    assert login(client).status_code == 200


def test_global_limit_covers_rotating_forwarded_addresses(client):
    for i in range(A.GLOBAL_FAILS):
        login(client, "guess", headers={**ORIGIN, "X-Forwarded-For": f"10.0.0.{i}"})
    assert login(client, headers={**ORIGIN, "X-Forwarded-For": "10.9.9.9"}).status_code == 429


def test_sessions_expire_when_idle_and_absolutely(client):
    assert login(client).status_code == 200
    client.t[0] += A.IDLE_TTL_S + 1
    assert client.get("/api/fixtures").status_code == 401
    assert login(client).status_code == 200
    for _ in range(7):
        client.t[0] += A.IDLE_TTL_S - 60
        client.get("/api/fixtures")
    assert client.get("/api/fixtures").status_code == 401  # past 12 h even while active


def test_security_headers_on_every_response(client):
    r = client.get("/api/session")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" in client.get("/api/session", headers={"X-Forwarded-Proto": "https"}).headers


def test_test_bypass_never_applies_through_a_tunnel(monkeypatch, client):
    monkeypatch.setenv("TIWALA_AUTH_DISABLED", "1")
    assert client.get("/api/fixtures").status_code == 401  # TestClient is not loopback
