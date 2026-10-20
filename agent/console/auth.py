"""Owner login for the console, so it can sit behind a public tunnel.

  * Password: stored only as a salted scrypt hash in .env (TIWALA_ADMIN_PASS_HASH). Set it with
        cd agent && ../.venv/bin/python -m console.auth set-password <username>
  * Sessions: 256-bit random ids kept server-side (only their SHA-256), in an HttpOnly, SameSite=Strict cookie,
    marked Secure on HTTPS. 12 h absolute and 2 h idle expiry; logout deletes the session.
  * Brute force: per-client and global failure limits with lockout; a wrong username costs the same scrypt run.
  * CSRF: state-changing requests must come from this origin (Origin or Referer) and carry X-Tiwala: 1.
  * Public paths: the login page and built assets (no data), POST /api/login, the WhatsApp webhook (its own
    Meta signature check) and the supplier console API (its own per-supplier token). Everything else needs a session.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

COOKIE = "tiwala_session"
SESSION_TTL_S = 12 * 3600
IDLE_TTL_S = 2 * 3600
CLIENT_FAILS, CLIENT_WINDOW_S = 5, 15 * 60  # per client: 5 failures per 15 min, then locked for the window
GLOBAL_FAILS, GLOBAL_WINDOW_S = 30, 15 * 60  # all clients together, in case the client address is spoofed
SCRYPT = {"n": 2 ** 17, "r": 8, "p": 1, "maxmem": 256 * 1024 * 1024, "dklen": 32}
MIN_PASSWORD, MAX_PASSWORD = 15, 256


class LoginThrottled(Exception):
    def __init__(self, seconds: float):
        self.seconds = max(1, int(seconds) + 1)
        super().__init__("Too many sign-in attempts. Please wait and try again.")

PUBLIC_EXACT = {"/api/login", "/api/session", "/webhooks/whatsapp"}
PUBLIC_PREFIX = ("/assets/", "/api/supplier")  # supplier API checks its own per-supplier token


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT["n"], SCRYPT["r"], SCRYPT["p"],
                                       base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, dk = stored.split("$")
        assert kind == "scrypt"
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=SCRYPT["maxmem"], dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except Exception:
        return False


_DUMMY = hash_password(secrets.token_hex(16))  # fallback when credentials have not been configured


class Auth:
    def __init__(self, user: str, pass_hash: str, clock=time.time):
        self.user, self.pass_hash, self.clock = user, pass_hash, clock
        self.sessions: dict[str, dict] = {}  # sha256(session id) -> {"created", "seen"}
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self.login_lock = threading.Lock()  # one memory-hard password check at a time

    @staticmethod
    def from_env() -> "Auth":
        return Auth(os.environ.get("TIWALA_ADMIN_USER", ""), os.environ.get("TIWALA_ADMIN_PASS_HASH", ""))

    @property
    def configured(self) -> bool:
        return bool(self.user and self.pass_hash.startswith("scrypt$"))

    # ------------------------------------------------------------ brute force

    def _recent(self, key: str, window: float) -> list[float]:
        now = self.clock()
        xs = [t for t in self.fails.get(key, []) if now - t < window]
        self.fails[key] = xs
        return xs

    def locked_for(self, client: str) -> float:
        with self.lock:
            for key, cap, window in ((f"c:{client}", CLIENT_FAILS, CLIENT_WINDOW_S), ("*", GLOBAL_FAILS, GLOBAL_WINDOW_S)):
                xs = self._recent(key, window)
                if len(xs) >= cap:
                    return max(1.0, xs[0] + window - self.clock())
        return 0.0

    def login(self, client: str, user: str, password: str) -> Optional[str]:
        """Serialize checks and recheck limits inside the admission lock, before scrypt."""
        if not self.login_lock.acquire(blocking=False):
            raise LoginThrottled(1)
        try:
            wait = self.locked_for(client)
            if wait:
                raise LoginThrottled(wait)
            ok_user = hmac.compare_digest(user.strip().lower().encode(), self.user.lower().encode())
            bounded = 0 < len(user) <= 64 and 0 < len(password) <= MAX_PASSWORD
            ok = check_password(password if bounded else "", self.pass_hash if self.configured else _DUMMY)
            ok = ok and ok_user and bounded and self.configured
            with self.lock:
                self.fails = {k: [t for t in ts if self.clock() - t < GLOBAL_WINDOW_S]
                              for k, ts in self.fails.items() if ts and self.clock() - ts[-1] < GLOBAL_WINDOW_S}
                if not ok:
                    now = self.clock()
                    self.fails.setdefault(f"c:{client}", []).append(now)
                    self.fails.setdefault("*", []).append(now)
                    return None
                self.fails.pop(f"c:{client}", None)
                sid = secrets.token_urlsafe(32)
                now = self.clock()
                # Remove expired sessions and cap retained sessions for this single owner.
                self.sessions = {k: v for k, v in self.sessions.items()
                                 if now - v["created"] <= SESSION_TTL_S and now - v["seen"] <= IDLE_TTL_S}
                if len(self.sessions) >= 32:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[_h(sid)] = {"created": now, "seen": now}
                return sid
        finally:
            self.login_lock.release()

    def valid(self, sid: Optional[str]) -> bool:
        if not sid:
            return False
        with self.lock:
            s = self.sessions.get(_h(sid))
            now = self.clock()
            if s is None or now - s["created"] > SESSION_TTL_S or now - s["seen"] > IDLE_TTL_S:
                self.sessions.pop(_h(sid), None)
                return False
            s["seen"] = now
            return True

    def logout(self, sid: Optional[str]) -> None:
        if sid:
            with self.lock:
                self.sessions.pop(_h(sid), None)


def _h(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


def trusted_proxy(request: Request) -> bool:
    """Opt in only when a reverse proxy strips and rewrites all forwarded headers."""
    peers = {p.strip() for p in os.environ.get("TIWALA_TRUSTED_PROXIES", "").split(",") if p.strip()}
    return request.client is not None and request.client.host in peers


def client_of(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "") if trusted_proxy(request) else ""
    # Use the nearest proxy's appended address, rather than a client-controlled first entry.
    return (fwd.split(",")[-1].strip() if fwd else "") or (request.client.host if request.client else "?")


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or (trusted_proxy(request)
            and request.headers.get("x-forwarded-proto", "") == "https")


def same_origin(request: Request) -> bool:
    host = request.headers.get("host", "")
    if trusted_proxy(request):
        host = request.headers.get("x-forwarded-host") or host
    src = request.headers.get("origin") or request.headers.get("referer") or ""
    try:
        origin = urlsplit(src)
        target = urlsplit(("https" if is_https(request) else "http") + "://" + host)
        return (origin.scheme in ("http", "https") and origin.username is None
                and origin.password is None and origin.hostname is not None
                and (origin.scheme, origin.hostname, origin.port if origin.port is not None else (443 if origin.scheme == "https" else 80))
                == (target.scheme, target.hostname, target.port if target.port is not None else (443 if target.scheme == "https" else 80)))
    except ValueError:
        return False


def is_public(path: str) -> bool:
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIX):
        return True
    return not path.startswith(("/api/", "/webhooks/", "/docs", "/openapi", "/redoc"))  # the SPA shell, no data


SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Cache-Control": "no-store",
}


def install(app, auth: Auth) -> None:
    """Middleware that gates every non-public path on a valid session, behind a request-size cap."""
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if not test_bypass(request) and not is_public(path):
            if not auth.valid(request.cookies.get(COOKIE)):
                return _with_headers(JSONResponse({"detail": "Please sign in."}, 401), request)
            if request.method not in ("GET", "HEAD", "OPTIONS") and not (
                    same_origin(request) and request.headers.get("x-tiwala") == "1"):
                return _with_headers(JSONResponse({"detail": "Cross-site request refused."}, 403), request)
        resp = await call_next(request)
        return _with_headers(resp, request)


MAX_BODY = 256 * 1024  # chat, supplier moves and Meta webhooks are a few KB; refuse anything far larger


class BodyLimit:
    """Refuses request bodies over MAX_BODY before anything parses them: by Content-Length when sent, and by
    counting chunks for chunked uploads. Public paths (login, webhook, supplier API) are covered too."""

    def __init__(self, app, limit: int = MAX_BODY):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.limit):
            return await JSONResponse({"detail": "Request body too large."}, 413)(scope, receive, send)
        seen = 0

        async def counted():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    raise ValueError("request body too large")
            return msg
        try:
            await self.app(scope, counted, send)
        except ValueError as e:
            if "too large" not in str(e):
                raise
            await JSONResponse({"detail": "Request body too large."}, 413)(scope, receive, send)


def test_bypass(request: Request) -> bool:
    """UI screenshot runs only: TIWALA_AUTH_DISABLED=1 and a direct loopback request (never through a tunnel)."""
    return (os.environ.get("TIWALA_AUTH_DISABLED") == "1" and request.client is not None
            and request.client.host in ("127.0.0.1", "::1")
            and not any(h in request.headers for h in ("x-forwarded-for", "x-forwarded-host", "forwarded")))


def _with_headers(resp, request: Request):
    for k, v in SECURITY_HEADERS.items():
        if k == "Cache-Control" and request.url.path.startswith("/assets/"):
            continue
        resp.headers.setdefault(k, v)
    if is_https(request):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


def set_password_cli(argv: list[str]) -> int:
    """python -m console.auth set-password <username>: prompts twice, writes the hash to .env, never the password."""
    if len(argv) != 2 or argv[0] != "set-password":
        print(__doc__)
        return 1
    if not argv[1] or len(argv[1]) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in argv[1]):
        print("Username must be 1–64 letters, digits, dots, underscores or hyphens. Nothing changed.")
        return 1
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat: ") or not MIN_PASSWORD <= len(pw) <= MAX_PASSWORD:
        print("Passwords differ or are not 15–256 characters long. Nothing changed.")
        return 1
    write_env({"TIWALA_ADMIN_USER": argv[1], "TIWALA_ADMIN_PASS_HASH": hash_password(pw)})
    print(f"Saved a scrypt hash for {argv[1]} in .env. Restart the console.")
    return 0


def write_env(values: dict[str, str], env: Path = Path(__file__).resolve().parents[2] / ".env") -> None:
    lines = env.read_text().splitlines() if env.exists() else []
    keys = set(values)
    out = [l for l in lines if l.split("=", 1)[0].strip() not in keys]
    out += [f"{k}='{v}'" for k, v in values.items()]  # quoted: the scrypt hash contains "$"
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only, like the keys beside it
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(env, 0o600)


if __name__ == "__main__":
    sys.exit(set_password_cli(sys.argv[1:]))
