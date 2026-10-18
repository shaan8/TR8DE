"""WhatsApp Business Platform (Cloud API) adapter and a local simulator that share one code path.

Meta specifics used here (checked against developers.facebook.com and the WhatsApp Business Messaging Policy,
October 2026; recheck before going live):
  * Webhook verification: GET with hub.mode=subscribe, hub.verify_token, hub.challenge; echo the challenge.
  * Event POSTs carry X-Hub-Signature-256: sha256=<HMAC-SHA256 of the raw body with the app secret>.
  * Deliveries can repeat (retries for up to days, all subscribed apps): dedupe on the message id.
  * value.messages[] (from, id, timestamp, type, text.body, context.id) and value.statuses[] (id, status, ...).
  * Send: POST https://graph.facebook.com/<version>/<phone-number-id>/messages with a bearer token.
  * Free-form replies only inside the 24-hour customer service window opened by the supplier's last message;
    outside it only an approved template may be sent. Business-initiated contact needs opt-in; honour opt-outs;
    automation needs a clear human escalation path.

Nothing is sent to Meta unless WHATSAPP_LIVE_SEND=1, all credentials are set, and the recipient is listed in
WHATSAPP_ALLOWED_RECIPIENTS. The simulator never contacts anyone and labels every message "simulator".
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

WINDOW_S = 24 * 3600
STOP_RX = re.compile(r"^\s*(stop|unsubscribe|opt ?out|huwag na)\s*[.!]*\s*$", re.I)
START_RX = re.compile(r"^\s*(start|subscribe|opt ?in)\s*[.!]*\s*$", re.I)
HUMAN_RX = re.compile(r"\b(human|person|agent|tao|talk to (someone|a person))\b", re.I)


def redact(wa_id: str) -> str:
    """Phone-number ids in logs and the UI: keep the last 4 digits only."""
    w = wa_id or ""
    if w.startswith(("sim:", "agent:", "supplier-console:")):  # not phone numbers: keep the kind, shorten the address
        kind, _, rest = w.partition(":")
        return f"{kind}:{rest[:6]}…{rest[-4:]}" if len(rest) > 12 else w
    d = re.sub(r"\D", "", w)
    return f"+••••{d[-4:]}" if len(d) >= 4 else "••••"


@dataclass(frozen=True)
class Config:
    access_token: str = ""
    phone_number_id: str = ""
    app_secret: str = ""
    verify_token: str = ""
    graph_version: str = "v23.0"
    template_name: str = ""  # approved template for messages outside the 24-hour window
    template_lang: str = "en"
    live_send: bool = False
    allowed: tuple = ()

    @staticmethod
    def from_env() -> "Config":
        e = os.environ.get
        return Config(e("WHATSAPP_ACCESS_TOKEN", ""), e("WHATSAPP_PHONE_NUMBER_ID", ""), e("WHATSAPP_APP_SECRET", ""),
                      e("WHATSAPP_VERIFY_TOKEN", ""), e("WHATSAPP_GRAPH_VERSION", "v23.0"),
                      e("WHATSAPP_TEMPLATE_NAME", ""), e("WHATSAPP_TEMPLATE_LANG", "en"),
                      e("WHATSAPP_LIVE_SEND", "0") == "1",
                      tuple(x.strip() for x in e("WHATSAPP_ALLOWED_RECIPIENTS", "").split(",") if x.strip()))

    @property
    def can_receive(self) -> bool:
        return bool(self.app_secret and self.verify_token)

    @property
    def can_send(self) -> bool:
        return bool(self.live_send and self.access_token and self.phone_number_id)

    def status(self) -> dict:
        """Safe to show: which pieces are configured, never their values."""
        return {"receive": self.can_receive, "send": self.can_send, "template": bool(self.template_name),
                "allowed_recipients": len(self.allowed), "graph_version": self.graph_version, "missing": self.missing()}

    def missing(self) -> list[str]:
        """Why a live WhatsApp send or receive would fail right now, in plain words (names only, no values)."""
        out = []
        empty = [k for k, v in (("WHATSAPP_ACCESS_TOKEN", self.access_token),
                                ("WHATSAPP_PHONE_NUMBER_ID", self.phone_number_id)) if not v]
        if empty:
            out.append(f"Missing Meta credentials in .env: {' and '.join(empty)}.")
        if not self.live_send:
            out.append("Live sending is off: WHATSAPP_LIVE_SEND is not 1.")
        if not self.allowed:
            out.append("No WHATSAPP_ALLOWED_RECIPIENTS: every live recipient is refused.")
        if not self.can_receive:
            out.append("Supplier replies cannot arrive: WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN are empty, and Meta "
                       "needs a public HTTPS webhook URL (localhost is unreachable).")
        if not self.template_name:
            out.append("No approved template (WHATSAPP_TEMPLATE_NAME): a first message, or one sent more than 24 h after "
                       "the supplier's last message, is blocked.")
        return out


# ---------------------------------------------------------------------- webhook primitives


def verify_subscription(cfg: Config, mode: str, token: str, challenge: str) -> Optional[str]:
    if cfg.verify_token and mode == "subscribe" and hmac.compare_digest(token or "", cfg.verify_token):
        return challenge
    return None


def valid_signature(cfg: Config, raw: bytes, header: str) -> bool:
    if not cfg.app_secret or not header or not header.startswith("sha256="):
        return False
    want = hmac.new(cfg.app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header[7:])


@dataclass
class Inbound:
    id: str
    wa_id: str
    ts: int
    text: str
    kind: str = "text"
    context_id: str = ""  # the message being replied to, if any
    phone_number_id: str = ""


@dataclass
class StatusUpdate:
    id: str
    status: str  # sent | delivered | read | failed
    ts: int
    wa_id: str = ""
    error: str = ""


def parse_webhook(payload: dict) -> tuple[list[Inbound], list[StatusUpdate]]:
    msgs, sts = [], []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return msgs, sts
    for entry in payload.get("entry") or []:
        for ch in entry.get("changes") or []:
            if ch.get("field") != "messages":
                continue
            v = ch.get("value") or {}
            pnid = (v.get("metadata") or {}).get("phone_number_id", "")
            for m in v.get("messages") or []:
                kind = m.get("type", "")
                body = (m.get("text") or {}).get("body", "") if kind == "text" else ""
                if kind == "button":
                    body = (m.get("button") or {}).get("text", "")
                msgs.append(Inbound(str(m.get("id", "")), str(m.get("from", "")), int(m.get("timestamp", 0) or 0),
                                    body, kind, str((m.get("context") or {}).get("id", "")), pnid))
            for s in v.get("statuses") or []:
                err = "; ".join(str(e.get("title") or e.get("code")) for e in s.get("errors") or [])
                sts.append(StatusUpdate(str(s.get("id", "")), str(s.get("status", "")), int(s.get("timestamp", 0) or 0),
                                        str(s.get("recipient_id", "")), err))
    return msgs, sts


# ---------------------------------------------------------------------- state stores


class JsonStore:
    def __init__(self, path: Path, default):
        self.path, self.lock = Path(path), threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.default = default

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else json.loads(json.dumps(self.default))

    def write(self, data) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)


@dataclass
class Contact:
    supplier_address: str
    wa_id: str  # E.164 digits for live, "sim:<address>" for the simulator
    channel: str  # live | simulator
    opted_in_at: int = 0
    opt_in_source: str = ""  # how consent was collected, e.g. "signed supplier onboarding form 2026-10-12"
    opted_out_at: int = 0
    last_inbound_at: int = 0
    last_inbound_ts: int = 0  # provider timestamp of the newest message seen, for out-of-order detection

    @property
    def opted_in(self) -> bool:
        return self.opted_in_at > 0 and self.opted_out_at < self.opted_in_at

    def in_window(self, now: int) -> bool:
        return self.last_inbound_at > 0 and now - self.last_inbound_at < WINDOW_S


class Contacts:
    def __init__(self, root: Path):
        self.s = JsonStore(Path(root) / "contacts.json", {})

    def get_by_wa(self, wa_id: str) -> Optional[Contact]:
        d = self.s.read()
        return next((Contact(**c) for c in d.values() if c["wa_id"] == wa_id), None)

    def get(self, supplier_address: str) -> Optional[Contact]:
        c = self.s.read().get(supplier_address.lower())
        return Contact(**c) if c else None

    def put(self, c: Contact) -> None:
        with self.s.lock:
            d = self.s.read()
            d[c.supplier_address.lower()] = asdict(c)
            self.s.write(d)


class Seen:
    """Processed inbound message ids, so a redelivered webhook is a no-op."""

    def __init__(self, root: Path, keep: int = 5000):
        self.s, self.keep = JsonStore(Path(root) / "seen.json", []), keep

    def first_time(self, mid: str) -> bool:
        with self.s.lock:
            ids = self.s.read()
            if mid in ids:
                return False
            ids.append(mid)
            self.s.write(ids[-self.keep:])
            return True


class Outbox:
    def __init__(self, root: Path):
        self.s = JsonStore(Path(root) / "outbox.json", [])

    def add(self, rec: dict) -> dict:
        with self.s.lock:
            d = self.s.read()
            d.append(rec)
            self.s.write(d[-2000:])
            return rec

    def update(self, provider_id: str, **kw) -> bool:
        with self.s.lock:
            d = self.s.read()
            hit = False
            for r in d:
                if r.get("provider_id") == provider_id:
                    r.update(kw)
                    hit = True
            if hit:
                self.s.write(d)
            return hit

    def for_negotiation(self, nid: str) -> list[dict]:
        return [r for r in self.s.read() if r.get("negotiation") == nid]


# ---------------------------------------------------------------------- transports


def _post_json(url: str, body: dict, bearer: str) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": f"Bearer {bearer}",
                                                                   "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


class CloudSender:
    """Live Cloud API sends. Refuses anything not explicitly allowed."""

    def __init__(self, cfg: Config, post: Callable[[str, dict, str], dict] = _post_json):
        self.cfg, self.post = cfg, post

    def send(self, wa_id: str, text: str, template_params: Optional[list[str]] = None) -> tuple[bool, str, str]:
        c = self.cfg
        if not c.can_send:
            return False, "", "live sending is off (WHATSAPP_LIVE_SEND=0 or credentials missing)"
        if wa_id not in c.allowed:
            return False, "", "recipient is not in WHATSAPP_ALLOWED_RECIPIENTS"
        url = f"https://graph.facebook.com/{c.graph_version}/{c.phone_number_id}/messages"
        if template_params is not None:
            body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id, "type": "template",
                    "template": {"name": c.template_name, "language": {"code": c.template_lang},
                                 "components": [{"type": "body", "parameters": [{"type": "text", "text": p[:1000]}
                                                                                for p in template_params]}]}}
        else:
            body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": wa_id, "type": "text",
                    "text": {"preview_url": False, "body": text[:4096]}}
        try:
            r = self.post(url, body, c.access_token)
            return True, str(((r.get("messages") or [{}])[0]).get("id", "")), ""
        except Exception as e:  # report, never retry automatically: a retry could duplicate an offer
            return False, "", f"{type(e).__name__}: {str(e)[:160]}"


class Gateway:
    """Associates supplier conversations with negotiations and moves messages both ways.

    on_text(negotiation_id, text, identity, message_id, channel) is the negotiation engine's supplier_text;
    find_open(supplier_address) returns the supplier's open negotiation id; escalate(note) tells the owner."""

    def __init__(self, root: str | Path, cfg: Config, on_text: Callable, find_open: Callable[[str], Optional[str]],
                 escalate: Callable[[str, str], None], log: Callable[..., None], sender: Optional[CloudSender] = None,
                 clock: Callable[[], float] = time.time):
        root = Path(root)
        self.cfg, self.contacts, self.seen, self.outbox = cfg, Contacts(root), Seen(root), Outbox(root)
        self.on_text, self.find_open, self.escalate, self.log = on_text, find_open, escalate, log
        self.sender = sender or CloudSender(cfg)
        self.clock = clock

    def now(self) -> int:
        return int(self.clock())

    # ---------------------------------------------------------- outbound

    def send(self, nid: str, supplier_address: str, text: str, proposal_id: Optional[str] = None) -> dict:
        c = self.contacts.get(supplier_address)
        rec = {"id": f"out-{int(self.clock() * 1000)}-{len(text)}", "negotiation": nid, "proposal": proposal_id,
               "to": redact(c.wa_id) if c else "none", "text": text, "ts": self.now(), "status": "queued",
               "channel": c.channel if c else "none", "kind": "text"}
        if c is None:
            rec.update(status="blocked", error="no WhatsApp contact on file for this supplier")
        elif not c.opted_in:
            rec.update(status="blocked", error="the supplier has not opted in, or opted out")
        elif c.channel == "simulator":
            rec.update(status="delivered", provider_id=rec["id"], note="local simulator: not sent to WhatsApp")
        elif c.in_window(self.now()):
            ok, pid, err = self.sender.send(c.wa_id, text)
            rec.update(status="sent" if ok else "failed", provider_id=pid, error=err)
        elif self.cfg.template_name:
            ok, pid, err = self.sender.send(c.wa_id, text, template_params=[text[:1000]])
            rec.update(status="sent" if ok else "failed", provider_id=pid, error=err, kind="template")
        else:
            rec.update(status="blocked", error="outside the 24-hour window and no approved template configured")
        if rec["status"] in ("blocked", "failed"):
            self.escalate(nid, f"WhatsApp message not sent: {rec.get('error')}")
        self.log("whatsapp_out", negotiation=nid, to=rec["to"], status=rec["status"], channel=rec["channel"],
                 kind=rec["kind"], error=rec.get("error", ""))
        return self.outbox.add(rec)

    # ---------------------------------------------------------- inbound

    def handle(self, m: Inbound, channel: str) -> dict:
        """One inbound message, live or simulated. Idempotent on the message id."""
        if not m.id or not self.seen.first_time(f"{channel}:{m.id}"):
            self.log("whatsapp_duplicate", channel=channel, id=m.id[-12:])
            return {"status": "duplicate"}
        c = self.contacts.get_by_wa(m.wa_id)
        if c is None or c.channel != channel:
            self.log("whatsapp_unknown_sender", channel=channel, sender=redact(m.wa_id))
            return {"status": "ignored", "reason": "unknown sender"}  # never answer unverified numbers
        now = self.now()
        out_of_order = bool(m.ts and c.last_inbound_ts and m.ts < c.last_inbound_ts)
        c.last_inbound_at = now
        c.last_inbound_ts = max(c.last_inbound_ts, m.ts)
        nid = self.find_open(c.supplier_address)
        if STOP_RX.match(m.text):
            c.opted_out_at = now
            self.contacts.put(c)
            self.log("whatsapp_opt_out", supplier=c.supplier_address)
            if nid:
                self.escalate(nid, "The supplier opted out of WhatsApp. Contact them another way; nothing was accepted.")
            return {"status": "opted_out"}
        if START_RX.match(m.text):
            c.opted_in_at, c.opt_in_source = now, f"supplier sent '{m.text.strip()}' on {channel}"
            self.contacts.put(c)
            return {"status": "opted_in"}
        self.contacts.put(c)
        if not nid:
            return {"status": "ignored", "reason": "no open negotiation"}
        if out_of_order:
            self.log("whatsapp_out_of_order", negotiation=nid, id=m.id[-12:])
        if HUMAN_RX.search(m.text) and not re.search(r"\d", m.text):
            self.escalate(nid, "The supplier asked to talk to a person.")
            self.send(nid, c.supplier_address, "Thank you. A person from the buyer will contact you. Nothing was "
                                               "accepted or changed.")
            return {"status": "escalated", "negotiation": nid}
        try:
            n = self.on_text(nid, m.text, c.wa_id, m.id, channel)
        except Exception as e:
            self.log("whatsapp_error", negotiation=nid, error=f"{type(e).__name__}: {str(e)[:160]}")
            return {"status": "error", "error": str(e)[:160]}
        return {"status": "processed", "negotiation": nid, "state": n.state, "out_of_order": out_of_order}

    def status(self, s: StatusUpdate) -> None:
        if self.outbox.update(s.id, status=s.status, error=s.error):
            self.log("whatsapp_status", status=s.status, error=s.error)
