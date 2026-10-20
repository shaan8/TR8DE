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
    assert h1.startswith("scrypt$131072$8$1$") and h1 != h2 and "pw123456" not in h1
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


def test_global_limit_covers_rotating_forwarded_addresses(client, monkeypatch):
    monkeypatch.setenv("TIWALA_TRUSTED_PROXIES", "testclient")
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


def test_security_headers_on_every_response(client, monkeypatch):
    r = client.get("/api/session")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in client.get("/api/session", headers={"X-Forwarded-Proto": "https"}).headers
    monkeypatch.setenv("TIWALA_TRUSTED_PROXIES", "testclient")
    assert "strict-transport-security" in client.get("/api/session", headers={"X-Forwarded-Proto": "https"}).headers


def test_test_bypass_never_applies_through_a_tunnel(monkeypatch, client):
    monkeypatch.setenv("TIWALA_AUTH_DISABLED", "1")
    assert client.get("/api/fixtures").status_code == 401  # TestClient is not loopback


def test_unsigned_webhook_posts_are_refused_before_the_agent_is_built(client, monkeypatch):
    from console import negotiation_api
    monkeypatch.setattr(negotiation_api, "svc", lambda: (_ for _ in ()).throw(AssertionError("agent built")))
    assert client.post("/webhooks/whatsapp", content=b"{}", headers={"X-Hub-Signature-256": "sha256=00"}).status_code == 403
    assert client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=x&hub.challenge=1").status_code == 403


def test_origin_requires_matching_scheme_and_port_and_ignores_untrusted_proxy(client, monkeypatch):
    for origin in ("https://testserver", "http://testserver:8001", "http://testserver:0", "null", "http://user@testserver"):
        assert login(client, headers={**ORIGIN, "Origin": origin}).status_code == 403
    forged = {**ORIGIN, "Origin": "https://evil.example", "X-Forwarded-Host": "evil.example",
              "X-Forwarded-Proto": "https"}
    assert login(client, headers=forged).status_code == 403
    monkeypatch.setenv("TIWALA_TRUSTED_PROXIES", "testclient")
    proxy = {**ORIGIN, "Origin": "https://console.example", "X-Forwarded-Host": "console.example",
             "X-Forwarded-Proto": "https"}
    r = login(client, headers=proxy)
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()


def test_forwarded_addresses_cannot_evade_per_client_lockout(client):
    for n in range(A.CLIENT_FAILS):
        assert login(client, "guess", headers={**ORIGIN, "X-Forwarded-For": f"192.0.2.{n}"}).status_code == 401
    r = login(client, headers={**ORIGIN, "X-Forwarded-For": "192.0.2.200"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_relogin_revokes_previous_cookie_and_logout_revokes_new_cookie(client):
    assert login(client).status_code == 200
    old = client.cookies.get(A.COOKIE)
    assert login(client).status_code == 200
    new = client.cookies.get(A.COOKIE)
    assert old != new and not server._auth().valid(old) and server._auth().valid(new)
    client.post("/api/logout", headers=ORIGIN)
    assert not server._auth().valid(new)


def test_oversized_credentials_cannot_authenticate_by_truncation(client):
    assert login(client, user="Shaan" + "x" * 65).status_code == 422
    assert login(client, pw="x" * 257).status_code == 422
    assert login(client, pw="").status_code == 422


def test_legacy_hash_remains_usable():
    import base64
    import hashlib
    salt = b"legacy-test-salt"
    dk = hashlib.scrypt(b"old unique password", salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64*1024*1024)
    stored = "scrypt$32768$8$1$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()
    assert A.check_password("old unique password", stored)
    assert not A.check_password("wrong password", stored)


def test_concurrent_logins_do_not_bypass_admission_or_lockout(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    a = A.Auth("owner", A.hash_password("a unique long password"))
    entered, release = Event(), Event()
    def check(*_):
        entered.set()
        assert release.wait(5)
        return False
    monkeypatch.setattr(A, "check_password", check)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(a.login, "client", "owner", "wrong")
        try:
            assert entered.wait(5)
            with pytest.raises(A.LoginThrottled):
                a.login("client", "owner", "wrong")
        finally:
            release.set()
        assert attempt.result() is None
    a.fails["c:client"] = [a.clock()] * A.CLIENT_FAILS
    monkeypatch.setattr(A, "check_password", lambda *_: pytest.fail("scrypt must not run while locked"))
    with pytest.raises(A.LoginThrottled):
        a.login("client", "owner", "a unique long password")


def test_password_setup_rejects_short_passwords_and_unsafe_usernames(monkeypatch):
    monkeypatch.setattr(A, "write_env", lambda *_: pytest.fail("must not write invalid credentials"))
    monkeypatch.setattr(A.getpass, "getpass", lambda *_: "eight888")
    assert A.set_password_cli(["set-password", "owner"]) == 1
    assert A.set_password_cli(["set-password", "owner\nINJECT=value"]) == 1


def test_password_setup_accepts_passphrase_and_writes_only_hash(monkeypatch):
    saved = {}
    monkeypatch.setattr(A, "write_env", saved.update)
    monkeypatch.setattr(A.getpass, "getpass", lambda *_: "a unique long passphrase")
    assert A.set_password_cli(["set-password", "owner"]) == 0
    assert saved["TIWALA_ADMIN_USER"] == "owner"
    assert "a unique long passphrase" not in saved["TIWALA_ADMIN_PASS_HASH"]
    assert A.check_password("a unique long passphrase", saved["TIWALA_ADMIN_PASS_HASH"])
