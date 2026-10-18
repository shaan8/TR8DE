"""Read-only balance connectors: banks via Plaid, PayPal and Stripe. These are the only source of off-chain
balances: there is no manual entry, and no amount is ever stored or accepted from a user, a file or a model.

Security properties, enforced here in code:
  * Read-only. Each adapter calls one balance endpoint and nothing that moves money. Stripe keys must be
    restricted keys, and a probe refuses any key that can also read charges. PayPal links require the
    reporting scope and record any extra scopes as a warning.
  * Pinned egress. HTTPS only, to an allowlist of provider hosts, no redirects, 10 s timeout.
  * Secrets stay in the Vault (Fernet, encrypted at rest). They never leave this module: not to callers,
    not to the audit log, not to any LLM.
  * Field allowlist. Adapters keep provider, balance, currency and time; raw responses are dropped, so
    account numbers, masks and names never get past the parser.
  * Provider-only amounts. Balances are fetched live over the pinned HTTPS connection and held in memory
    for CACHE_TTL_S. links.json stores only link metadata; a record without a valid provider token yields
    nothing, and the provider hosts and FX table are fixed in code. Balances older than MAX_AGE_S are dropped.
  * Consent. Nothing is linked without an explicit consent record; removing a link deletes its secrets
    and, for Plaid, revokes the item at the provider.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken

from .data import AccountBalance
from .models import PHP

MAX_AGE_S = 24 * 3600
CACHE_TTL_S = 120
TIMEOUT_S = 10
CONSENT_SCOPE = "Read account balances only. Tiwala cannot move money from this account."

ALLOWED_HOSTS = {
    "sandbox.plaid.com", "production.plaid.com",
    "api-m.sandbox.paypal.com", "api-m.paypal.com",
    "api.stripe.com",
}
PLAID_HOSTS = {"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}
PAYPAL_HOSTS = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
PAYPAL_READ_SCOPE = "https://uri.paypal.com/services/reporting/search/read"
PLAID_LIQUID = {"checking", "savings", "money market", "cash management"}
PLAID_SANDBOX_BANKS = {"First Platypus Bank": "ins_109508", "Tartan Bank": "ins_109511",
                       "Houndstooth Bank": "ins_109512"}
ZERO_DECIMAL = {"jpy", "krw", "vnd", "clp", "isk", "ugx"}

# Indicative PHP per unit, for the forecast only (never for payments). Fixed in code: no runtime override.
FX = {"PHP": 1.0, "USD": 58.0, "EUR": 63.0, "GBP": 75.0, "CAD": 42.0, "SGD": 44.0, "CNY": 8.0,
              "HKD": 7.4, "AUD": 38.0, "JPY": 0.39}


class ConnectorError(Exception):
    """Safe to show the owner: never carries a secret or a raw provider response."""


def to_php_units(major: float, currency: str) -> Optional[int]:
    rate = FX.get(currency.upper())
    return None if rate is None else round(major * rate * PHP)


# ------------------------------------------------------------------ pinned HTTP


Http = Callable[..., requests.Response]


def pinned_request(method: str, url: str, **kw) -> requests.Response:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ConnectorError(f"Blocked outbound request to {u.hostname}: not a provider host.")
    return requests.request(method, url, timeout=TIMEOUT_S, allow_redirects=False, **kw)


def _json(r: requests.Response, what: str) -> dict:
    if r.status_code >= 400:
        raise ConnectorError(f"{what} refused the request (HTTP {r.status_code}).")
    try:
        return r.json()
    except ValueError:
        raise ConnectorError(f"{what} returned an unreadable response.")


# ------------------------------------------------------------------ adapters


@dataclass
class Fetched:
    label: str
    major: float
    currency: str
    as_of: int


class Plaid:
    """Banks through Plaid. The platform holds PLAID_CLIENT_ID/PLAID_SECRET; each linked bank is an
    access token in the vault. Production links come from Plaid Link (public token -> exchange); in the
    sandbox, `sandbox_public_token` stands in for the Link screen."""
    name = "plaid"

    def __init__(self, http: Http = pinned_request, env: Optional[str] = None):
        self.http = http
        self.env = env or os.environ.get("PLAID_ENV", "sandbox")
        if self.env not in PLAID_HOSTS:
            raise ConnectorError(f"PLAID_ENV must be one of {sorted(PLAID_HOSTS)}.")
        self.base = PLAID_HOSTS[self.env]

    def _creds(self) -> dict:
        cid, sec = os.environ.get("PLAID_CLIENT_ID"), os.environ.get("PLAID_SECRET")
        if not (cid and sec):
            raise ConnectorError("Set PLAID_CLIENT_ID and PLAID_SECRET in .env to link banks.")
        return {"client_id": cid, "secret": sec}

    def _post(self, path: str, body: dict) -> dict:
        return _json(self.http("POST", self.base + path, json={**self._creds(), **body}), "Plaid")

    def sandbox_public_token(self, institution_id: str) -> str:
        if self.env != "sandbox":
            raise ConnectorError("Sandbox linking is only available with PLAID_ENV=sandbox.")
        return self._post("/sandbox/public_token/create",
                          {"institution_id": institution_id, "initial_products": ["auth"]})["public_token"]

    def exchange(self, public_token: str) -> dict:
        j = self._post("/item/public_token/exchange", {"public_token": public_token})
        return {"access_token": j["access_token"], "item_id": j["item_id"]}

    def fetch(self, secret: dict) -> list[Fetched]:
        j = self._post("/accounts/balance/get", {"access_token": secret["access_token"]})
        now, out = int(time.time()), []
        for a in j.get("accounts", []):
            if a.get("type") != "depository" or a.get("subtype") not in PLAID_LIQUID:
                continue  # credit lines, loans and investments are not spendable cash
            b = a.get("balances") or {}
            amt = b.get("available") if b.get("available") is not None else b.get("current")
            cur = b.get("iso_currency_code")
            if amt is None or not cur:
                continue
            out.append(Fetched(str(a["subtype"]), float(amt), cur, now))
        return out

    def revoke(self, secret: dict) -> None:
        self._post("/item/remove", {"access_token": secret["access_token"]})


class PayPal:
    """The owner's own PayPal REST app (client id + secret), reporting API only."""
    name = "paypal"

    def __init__(self, http: Http = pinned_request):
        self.http = http

    def _base(self, secret: dict) -> str:
        env = secret.get("env", "sandbox")
        if env not in PAYPAL_HOSTS:
            raise ConnectorError("PayPal environment must be sandbox or live.")
        return PAYPAL_HOSTS[env]

    def token(self, secret: dict) -> tuple[str, set[str]]:
        basic = base64.b64encode(f"{secret['client_id']}:{secret['client_secret']}".encode()).decode()
        j = _json(self.http("POST", self._base(secret) + "/v1/oauth2/token", data={"grant_type": "client_credentials"},
                            headers={"Authorization": f"Basic {basic}"}), "PayPal")
        return j["access_token"], set((j.get("scope") or "").split())

    def check_scope(self, secret: dict) -> list[str]:
        """On link: require the read scope; return a warning for each extra (non-read) scope family."""
        _, scopes = self.token(secret)
        if PAYPAL_READ_SCOPE not in scopes:
            raise ConnectorError("This PayPal app lacks Transaction Search (reporting read). "
                                 "Enable it under the app's Features, then link again.")
        extra = sorted(s for s in scopes if "payments" in s or "payouts" in s or "vault" in s)
        return ["PayPal app credentials also allow payments; Tiwala only calls the read-only balances "
                "endpoint. Production would use PayPal partner consent scoped to read."] if extra else []

    def fetch(self, secret: dict) -> list[Fetched]:
        tok, _ = self.token(secret)
        j = _json(self.http("GET", self._base(secret) + "/v1/reporting/balances",
                            headers={"Authorization": f"Bearer {tok}"}), "PayPal")
        as_of = _iso(j.get("last_refresh_time") or j.get("as_of_time")) or int(time.time())
        out = []
        for b in j.get("balances", []):
            money = b.get("available_balance") or b.get("total_balance") or {}
            if money.get("value") is None:
                continue
            out.append(Fetched("balance", float(money["value"]), money.get("currency_code") or b.get("currency"), as_of))
        return out


class Stripe:
    """The owner's Stripe account via a restricted key with only Balance: Read."""
    name = "stripe"

    def __init__(self, http: Http = pinned_request):
        self.http = http

    def _get(self, secret: dict, path: str) -> requests.Response:
        return self.http("GET", "https://api.stripe.com" + path, headers={"Authorization": f"Bearer {secret['api_key']}"})

    def check_scope(self, secret: dict) -> list[str]:
        key = secret["api_key"]
        if not key.startswith(("rk_test_", "rk_live_")):
            raise ConnectorError("Use a Stripe restricted key (rk_...) with only Balance: Read. "
                                 "Full secret keys can move money and are refused.")
        if self._get(secret, "/v1/charges?limit=1").status_code < 400:
            raise ConnectorError("This restricted key can read charges. Create one with only Balance: Read.")
        _json(self._get(secret, "/v1/balance"), "Stripe")
        return []

    def fetch(self, secret: dict) -> list[Fetched]:
        j = _json(self._get(secret, "/v1/balance"), "Stripe")
        now, out = int(time.time()), []
        for b in j.get("available", []):  # pending funds are not spendable yet
            cur = (b.get("currency") or "").lower()
            div = 1 if cur in ZERO_DECIMAL else 100
            out.append(Fetched("available", int(b.get("amount", 0)) / div, cur.upper(), now))
        return out


def _iso(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


PROVIDER_LABEL = {"plaid": "Bank (Plaid)", "paypal": "PayPal", "stripe": "Stripe"}


# ------------------------------------------------------------------ vault


class Vault:
    """Secrets per link, Fernet-encrypted at rest. Key from TIWALA_VAULT_KEY, else a 0600 key file next to the
    data (fine for a laptop demo; production keeps the key in an OS keychain or KMS)."""

    def __init__(self, path: Path, key: Optional[str] = None):
        self.path = Path(path)
        key = key or os.environ.get("TIWALA_VAULT_KEY")
        self.key_source = "env" if key else "file"
        if not key:
            kf = self.path.with_name(".vault.key")
            if not kf.exists():
                kf.parent.mkdir(parents=True, exist_ok=True)
                kf.write_bytes(Fernet.generate_key())
                kf.chmod(0o600)
            key = kf.read_text().strip()
        self._f = Fernet(key.encode() if isinstance(key, str) else key)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self._f.decrypt(self.path.read_bytes()))
        except InvalidToken:
            raise ConnectorError("Vault cannot be decrypted with this key.")

    def _save(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(json.dumps(d).encode()))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def put(self, link_id: str, secret: dict) -> None:
        d = self._load()
        d[link_id] = secret
        self._save(d)

    def get(self, link_id: str) -> Optional[dict]:
        return self._load().get(link_id)

    def delete(self, link_id: str) -> None:
        d = self._load()
        if d.pop(link_id, None) is not None:
            self._save(d)


# ------------------------------------------------------------------ registry


@dataclass
class LinkStatus:
    id: str
    provider: str
    label: str
    balances: list[AccountBalance]
    warnings: list[str]
    error: str = ""


class Registry:
    """Linked accounts (links.json, no secrets) + vault + a short balance cache."""

    def __init__(self, data_dir: Path, http: Http = pinned_request, vault: Optional[Vault] = None,
                 now: Callable[[], float] = time.time):
        self.data = Path(data_dir)
        self.path = self.data / "links.json"
        self.vault = vault or Vault(self.data / "vault.bin")
        self.http, self.now = http, now
        self.adapters = {"plaid": lambda: Plaid(http), "paypal": lambda: PayPal(http), "stripe": lambda: Stripe(http)}
        self._cache: dict[str, tuple[float, LinkStatus]] = {}  # memory only; amounts never touch disk

    # ---- storage
    def links(self) -> list[dict]:
        """Link metadata only. Anything that is not a provider link (e.g. a hand-written record) is ignored."""
        raw = json.loads(self.path.read_text()) if self.path.exists() else []
        return [l for l in raw if isinstance(l, dict) and l.get("provider") in self.adapters and l.get("id")]

    def _save(self, links: list[dict]) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(links, indent=2))

    def _record(self, provider: str, label: str, warnings: list[str]) -> dict:
        return {"id": secrets.token_hex(6), "provider": provider, "label": label[:40], "created_at": int(self.now()),
                "consent": {"given_at": int(self.now()), "scope": CONSENT_SCOPE}, "warnings": warnings}

    # ---- linking (every path requires consent=True)
    @staticmethod
    def _need_consent(consent: bool) -> None:
        if consent is not True:
            raise ConnectorError("Linking needs your explicit consent to read balances.")

    def _store(self, rec: dict, secret: dict) -> dict:
        self.vault.put(rec["id"], secret)
        self._save(self.links() + [rec])
        return {k: v for k, v in rec.items() if k != "consent"}

    def link_plaid_sandbox(self, institution_id: str, label: str, consent: bool) -> dict:
        self._need_consent(consent)
        p = Plaid(self.http)
        return self.link_plaid(p.sandbox_public_token(institution_id), label, consent)

    def link_plaid(self, public_token: str, label: str, consent: bool) -> dict:
        self._need_consent(consent)
        p = Plaid(self.http)
        secret = {**p.exchange(public_token), "env": p.env}
        if not p.fetch(secret):
            raise ConnectorError("No checking or savings accounts found at this bank.")
        return self._store(self._record("plaid", label or "Bank", []), secret)

    def link_paypal(self, client_id: str, client_secret: str, env: str, label: str, consent: bool) -> dict:
        self._need_consent(consent)
        secret = {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "env": env}
        pp = PayPal(self.http)
        warnings = pp.check_scope(secret)
        pp.fetch(secret)
        return self._store(self._record("paypal", label or "PayPal", warnings), secret)

    def link_stripe(self, api_key: str, label: str, consent: bool) -> dict:
        self._need_consent(consent)
        secret = {"api_key": api_key.strip()}
        warnings = Stripe(self.http).check_scope(secret)
        return self._store(self._record("stripe", label or "Stripe", warnings), secret)

    def remove(self, link_id: str) -> bool:
        links = self.links()
        rec = next((l for l in links if l["id"] == link_id), None)
        if rec is None:
            return False
        secret = self.vault.get(link_id)
        if rec["provider"] == "plaid" and secret:
            try:
                Plaid(self.http, secret.get("env")).revoke(secret)
            except ConnectorError:
                pass  # still forget it locally
        self.vault.delete(link_id)
        self._save([l for l in links if l["id"] != link_id])
        self._cache.pop(link_id, None)
        return True

    # ---- reading
    def status(self, refresh: bool = False) -> list[LinkStatus]:
        out = []
        for rec in self.links():
            hit = self._cache.get(rec["id"])
            if hit and not refresh and self.now() - hit[0] < CACHE_TTL_S:
                out.append(hit[1])
                continue
            s = self._read(rec)
            self._cache[rec["id"]] = (self.now(), s)
            out.append(s)
        return out

    def balances(self, refresh: bool = False) -> list[AccountBalance]:
        return [b for s in self.status(refresh) for b in s.balances]

    def _read(self, rec: dict) -> LinkStatus:
        base = PROVIDER_LABEL.get(rec["provider"], rec["provider"])
        name = f"{rec['label']}" if rec["label"] else base
        secret = self.vault.get(rec["id"])
        if not secret:
            return LinkStatus(rec["id"], rec["provider"], name, [], [], "Credentials missing. Link again.")
        try:
            fetched = self.adapters[rec["provider"]]().fetch(secret)
        except ConnectorError as e:
            return LinkStatus(rec["id"], rec["provider"], name, [], rec.get("warnings", []), str(e))
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return LinkStatus(rec["id"], rec["provider"], name, [], rec.get("warnings", []),
                              f"{base} could not be reached.")
        bals, warn = [], list(rec.get("warnings", []))
        for f in fetched:
            units = to_php_units(f.major, f.currency)
            if units is None:
                warn.append(f"Skipped a {f.currency} balance: no FX rate configured.")
                continue
            if self.now() - f.as_of > MAX_AGE_S:
                warn.append(f"{base} reported a balance over 24 h old; left out of the forecast.")
                continue
            bals.append(AccountBalance(name, units, "PHP", f.as_of, f"{base} · {f.label} · {f.currency} {f.major:,.2f}"))
        return LinkStatus(rec["id"], rec["provider"], name, bals, warn)
