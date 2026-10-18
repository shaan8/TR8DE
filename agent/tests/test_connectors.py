"""Balance connectors: read-only scope checks, pinned egress, field allowlist, secret handling,
provider-only amounts and consent. Provider APIs are replaced by a recorded fake; no network."""
import json
import time

import pytest
from cryptography.fernet import Fernet

from tiwala_agent import connectors as cx
from tiwala_agent.audit import AuditLog
from tiwala_agent.connectors import ConnectorError, Registry, Vault
from tiwala_agent.models import PHP

PLAID_ACCOUNTS = {"accounts": [
    {"account_id": "acc1", "mask": "M4SK-A", "name": "Plaid Checking", "official_name": "Plaid Gold Standard",
     "type": "depository", "subtype": "checking",
     "balances": {"available": 100, "current": 110, "iso_currency_code": "USD"}},
    {"account_id": "acc2", "mask": "M4SK-B", "type": "depository", "subtype": "savings",
     "balances": {"available": None, "current": 210, "iso_currency_code": "USD"}},
    {"account_id": "acc3", "mask": "3333", "type": "credit", "subtype": "credit card",
     "balances": {"available": 9000, "current": 410, "iso_currency_code": "USD"}},
    {"account_id": "acc4", "mask": "4444", "type": "depository", "subtype": "cd",
     "balances": {"available": None, "current": 1000, "iso_currency_code": "USD"}},
], "item": {"item_id": "item-1"}}


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeHttp:
    """Routes (method, url) to canned responses and records every call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, frag), resp in self.routes.items():
            if m == method and frag in url:
                return resp(kw) if callable(resp) else resp
        return Resp(404, {"error": "no route"})


def plaid_routes():
    return {
        ("POST", "/sandbox/public_token/create"): Resp(200, {"public_token": "public-sandbox-1"}),
        ("POST", "/item/public_token/exchange"): Resp(200, {"access_token": "access-sandbox-SECRET", "item_id": "item-1"}),
        ("POST", "/accounts/balance/get"): Resp(200, PLAID_ACCOUNTS),
        ("POST", "/item/remove"): Resp(200, {}),
    }


PAYPAL_TOKEN = {"access_token": "A21-PAYPAL-SECRET", "scope": f"{cx.PAYPAL_READ_SCOPE} openid"}
PAYPAL_BAL = {"balances": [{"currency": "USD", "primary": True,
                            "total_balance": {"currency_code": "USD", "value": "5100.00"},
                            "available_balance": {"currency_code": "USD", "value": "5000.00"}}],
              "account_id": "PAYERID123", "last_refresh_time": "2099-01-01T00:00:00Z"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "plaid-platform-SECRET")
    monkeypatch.setenv("PLAID_ENV", "sandbox")


def reg(tmp_path, routes, now=None):
    http = FakeHttp(routes)
    return Registry(tmp_path, http=http, vault=Vault(tmp_path / "vault.bin", Fernet.generate_key().decode()),
                    now=now or time.time), http


# ------------------------------------------------------------------ Plaid


def test_plaid_link_keeps_only_liquid_accounts_and_allowlisted_fields(tmp_path, env):
    r, _ = reg(tmp_path, plaid_routes())
    r.link_plaid_sandbox("ins_109508", "My bank", consent=True)
    bals = r.balances()
    assert [b.balance for b in bals] == [100 * 58 * PHP, 210 * 58 * PHP]  # available, else current; USD -> PHP
    dumped = json.dumps([b.__dict__ for b in bals])
    for leak in ("M4SK-A", "M4SK-B", "Gold Standard", "acc1", "access-sandbox-SECRET"):
        assert leak not in dumped


def test_secrets_never_in_links_file_audit_or_overview_and_vault_is_encrypted(tmp_path, env):
    r, _ = reg(tmp_path, plaid_routes())
    rec = r.link_plaid_sandbox("ins_109508", "My bank", consent=True)
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.write("account_linked", link_id=rec["id"], provider=rec["provider"])
    for f in ("links.json", "vault.bin", "audit.jsonl"):
        assert b"access-sandbox-SECRET" not in (tmp_path / f).read_bytes()
    assert "access-sandbox-SECRET" not in json.dumps(rec)
    assert r.vault.get(rec["id"])["access_token"] == "access-sandbox-SECRET"


def test_vault_with_wrong_key_refuses(tmp_path):
    Vault(tmp_path / "v.bin", Fernet.generate_key().decode()).put("x", {"t": "s"})
    with pytest.raises(ConnectorError):
        Vault(tmp_path / "v.bin", Fernet.generate_key().decode()).get("x")


def test_vault_key_file_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.delenv("TIWALA_VAULT_KEY", raising=False)
    v = Vault(tmp_path / "vault.bin")
    v.put("x", {"t": "s"})
    assert v.key_source == "file"
    assert (tmp_path / ".vault.key").stat().st_mode & 0o077 == 0
    assert (tmp_path / "vault.bin").stat().st_mode & 0o077 == 0


def test_remove_revokes_at_plaid_and_deletes_secret(tmp_path, env):
    r, http = reg(tmp_path, plaid_routes())
    rec = r.link_plaid_sandbox("ins_109508", "My bank", consent=True)
    assert r.remove(rec["id"])
    assert any("/item/remove" in c[1] for c in http.calls)
    assert r.vault.get(rec["id"]) is None and r.links() == [] and r.balances() == []


def test_revoked_token_shows_error_and_contributes_nothing(tmp_path, env):
    routes = plaid_routes()
    r, http = reg(tmp_path, routes)
    r.link_plaid_sandbox("ins_109508", "My bank", consent=True)
    routes[("POST", "/accounts/balance/get")] = Resp(400, {"error_code": "ITEM_LOGIN_REQUIRED",
                                                           "access_token": "access-sandbox-SECRET"})
    [s] = r.status(refresh=True)
    assert s.balances == [] and "HTTP 400" in s.error and "SECRET" not in s.error


# ------------------------------------------------------------------ PayPal


def paypal_routes(token=PAYPAL_TOKEN, bal=PAYPAL_BAL):
    return {("POST", "/v1/oauth2/token"): Resp(200, token), ("GET", "/v1/reporting/balances"): Resp(200, bal)}


def test_paypal_reads_available_balance(tmp_path):
    r, http = reg(tmp_path, paypal_routes())
    rec = r.link_paypal("client", "pp-client-SECRET", "sandbox", "Shop PayPal", consent=True)
    [b] = r.balances()
    assert b.balance == 5000 * 58 * PHP
    assert rec["warnings"] == []
    assert all(c[1].startswith("https://api-m.sandbox.paypal.com") for c in http.calls)
    assert "PAYERID123" not in json.dumps(b.__dict__)


def test_paypal_without_read_scope_is_refused(tmp_path):
    r, _ = reg(tmp_path, paypal_routes(token={"access_token": "t", "scope": "openid"}))
    with pytest.raises(ConnectorError, match="Transaction Search"):
        r.link_paypal("client", "secret", "sandbox", "", consent=True)
    assert r.links() == []


def test_paypal_payment_scopes_recorded_as_warning(tmp_path):
    tok = {"access_token": "t", "scope": f"{cx.PAYPAL_READ_SCOPE} https://uri.paypal.com/services/payments/payment"}
    r, _ = reg(tmp_path, paypal_routes(token=tok))
    rec = r.link_paypal("client", "secret", "sandbox", "", consent=True)
    assert rec["warnings"] and "allow payments" in rec["warnings"][0]


def test_stale_balance_is_left_out(tmp_path):
    old = dict(PAYPAL_BAL, last_refresh_time="2020-01-01T00:00:00Z")
    r, _ = reg(tmp_path, paypal_routes(bal=old))
    r.link_paypal("client", "secret", "sandbox", "", consent=True)
    [s] = r.status(refresh=True)
    assert s.balances == [] and any("24 h" in w for w in s.warnings)


# ------------------------------------------------------------------ Stripe


def stripe_routes(charges_status=403):
    return {("GET", "/v1/charges"): Resp(charges_status, {}),
            ("GET", "/v1/balance"): Resp(200, {"available": [{"amount": 123456, "currency": "usd"},
                                                             {"amount": 5000, "currency": "jpy"}],
                                               "pending": [{"amount": 999999, "currency": "usd"}]})}


@pytest.mark.parametrize("key", ["sk_test_abc", "sk_live_abc", "pk_test_abc", "whatever"])
def test_stripe_refuses_keys_that_are_not_restricted(tmp_path, key):
    r, http = reg(tmp_path, stripe_routes())
    with pytest.raises(ConnectorError, match="restricted key"):
        r.link_stripe(key, "", consent=True)
    assert http.calls == [] and r.links() == []


def test_stripe_refuses_restricted_key_with_extra_permissions(tmp_path):
    r, _ = reg(tmp_path, stripe_routes(charges_status=200))
    with pytest.raises(ConnectorError, match="Balance: Read"):
        r.link_stripe("rk_test_abc", "", consent=True)


def test_stripe_counts_available_only_and_handles_zero_decimal(tmp_path):
    r, _ = reg(tmp_path, stripe_routes())
    r.link_stripe("rk_test_abc", "Stripe", consent=True)
    bals = r.balances()
    assert [b.balance for b in bals] == [round(1234.56 * 58 * PHP), round(5000 * 0.39 * PHP)]


# ------------------------------------------------------------------ egress, consent, manual


@pytest.mark.parametrize("url", ["http://api.stripe.com/v1/balance", "https://evil.example/v1/balance",
                                 "https://api.stripe.com.evil.example/v1/balance", "https://169.254.169.254/latest"])
def test_pinned_egress_blocks_non_provider_hosts(url):
    with pytest.raises(ConnectorError, match="Blocked"):
        cx.pinned_request("GET", url)


def test_every_link_path_requires_consent(tmp_path, env):
    r, http = reg(tmp_path, {**plaid_routes(), **paypal_routes(), **stripe_routes()})
    for call in (lambda: r.link_plaid_sandbox("ins_109508", "", consent=False),
                 lambda: r.link_paypal("c", "s", "sandbox", "", consent=False),
                 lambda: r.link_stripe("rk_test_x", "", consent=False)):
        with pytest.raises(ConnectorError, match="consent"):
            call()
    assert http.calls == [] and r.links() == []


def test_no_way_to_enter_an_amount():
    assert not [m for m in dir(Registry) if "manual" in m or m.startswith("add")]


@pytest.mark.parametrize("record", [
    {"id": "x1", "provider": "manual", "label": "GCash", "amount": 1_000_000, "currency": "PHP"},
    {"id": "x2", "provider": "plaid", "label": "Fake bank", "amount": 1_000_000, "currency": "PHP"},
    {"provider": "stripe", "amount": 5},
])
def test_hand_written_links_yield_no_balance(tmp_path, env, record):
    """Editing links.json cannot create money: amounts come only from a provider call with a vaulted token."""
    r, http = reg(tmp_path, {**plaid_routes(), **stripe_routes()})
    (tmp_path / "links.json").write_text(json.dumps([record]))
    assert r.balances(refresh=True) == []
    assert not any("/balance" in c[1] for c in http.calls)


def test_legacy_accounts_file_is_ignored(tmp_path):
    (tmp_path / "accounts.json").write_text(json.dumps([
        {"provider": "GCash", "balance": 4_800_000, "currency": "PHP", "consent": True}]))
    r, _ = reg(tmp_path, {})
    assert r.balances() == [] and not (tmp_path / "links.json").exists()


def test_amounts_never_written_to_disk(tmp_path):
    r, _ = reg(tmp_path, paypal_routes())
    r.link_paypal("client", "secret", "sandbox", "Shop", consent=True)
    r.balances(refresh=True)
    assert "5000" not in (tmp_path / "links.json").read_text()


def test_fx_is_fixed_in_code(monkeypatch):
    monkeypatch.setenv("TIWALA_FX", '{"USD": 5000}')
    assert cx.to_php_units(10, "usd") == 580 * PHP
    assert cx.to_php_units(10, "ZZZ") is None
