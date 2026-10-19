"""Telegram Bot API adapter for supplier conversations, on the same Gateway rules as WhatsApp.

No webhook and no public URL: a background thread long-polls getUpdates (an outbound HTTPS request that Telegram
holds open until a message arrives), so it works from a laptop behind NAT. Replies go out with sendMessage.

Binding: the owner makes a one-time invite for a saved payee (CLI below or POST /api/telegram/invite). The supplier
opens https://t.me/<bot>?start=<code> and presses Start, which sends "/start <code>"; that private chat becomes the
supplier's contact, opted in by their own Start press. Codes are single use, expire, and are stored only as hashes.
Messages from chats that were never bound are ignored, as on WhatsApp. /stop opts out, /start opts back in.

Nothing is sent unless TELEGRAM_LIVE_SEND=1 and TELEGRAM_BOT_TOKEN is set. The token is never logged.

    python -m tiwala_agent.telegram invite "John the fruit guy"
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .whatsapp import Config, Contact, Gateway, Inbound, JsonStore

API = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")  # override only for local end-to-end tests
INVITE_TTL_S = 7 * 86400
POLL_TIMEOUT_S = 25
CODE_RX = re.compile(r"^[A-Za-z0-9_-]{8,64}$")  # Telegram deep-link start parameters: up to 64 of these characters


@dataclass(frozen=True)
class TgConfig:
    token: str = ""
    live_send: bool = False
    username: str = ""  # bot username for invite links; read from getMe when empty

    @staticmethod
    def from_env() -> "TgConfig":
        e = os.environ.get
        return TgConfig(e("TELEGRAM_BOT_TOKEN", "").strip(), e("TELEGRAM_LIVE_SEND", "0") == "1",
                        e("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@"))

    @property
    def can_send(self) -> bool:
        return bool(self.live_send and self.token)

    def status(self) -> dict:
        missing = []
        if not self.token:
            missing.append("No TELEGRAM_BOT_TOKEN in .env (create a bot with @BotFather).")
        if not self.live_send:
            missing.append("Live sending is off: TELEGRAM_LIVE_SEND is not 1.")
        return {"receive": bool(self.token), "send": self.can_send, "missing": missing}


def _call(token: str, method: str, body: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(f"{API}/bot{token}/{method}", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # Telegram explains failures in the JSON body
        try:
            out = json.loads(e.read().decode())
        except ValueError:
            out = {"ok": False, "description": f"HTTP {e.code}"}
    if not out.get("ok"):
        raise RuntimeError(str(out.get("description", "Telegram error"))[:160])
    return out.get("result")


def _clean(err: Exception, token: str) -> str:
    s = f"{type(err).__name__}: {str(err)[:160]}"
    return s.replace(token, "<token>") if token else s


class TelegramSender:
    """Same contract as whatsapp.CloudSender.send: (ok, provider message id, error)."""

    def __init__(self, cfg: TgConfig, call: Callable[[str, str, dict], dict] = _call):
        self.cfg, self.call = cfg, call

    def send(self, chat: str, text: str) -> tuple[bool, str, str]:
        if not self.cfg.can_send:
            return False, "", "live sending is off (TELEGRAM_LIVE_SEND=0 or no TELEGRAM_BOT_TOKEN)"
        chat_id = chat.removeprefix("tg:")
        if not chat_id.lstrip("-").isdigit():
            return False, "", "not a Telegram chat id"
        try:
            r = self.call(self.cfg.token, "sendMessage", {"chat_id": int(chat_id), "text": text[:4096],
                                                          "link_preview_options": {"is_disabled": True}})
            return True, f"tg:{chat_id}:{r.get('message_id', '')}", ""
        except Exception as e:  # report, never retry automatically: a retry could duplicate an offer
            return False, "", _clean(e, self.cfg.token)


class Invites:
    """One-time start codes, stored as SHA-256 hashes: a leaked data file does not reveal a usable link."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.s, self.clock = JsonStore(Path(root) / "telegram_invites.json", {}), clock

    @staticmethod
    def _h(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def create(self, supplier_address: str, ttl_s: int = INVITE_TTL_S) -> str:
        code = secrets.token_urlsafe(18)
        with self.s.lock:
            d = {k: v for k, v in self.s.read().items() if v["expires"] > self.clock() and not v.get("used")}
            d[self._h(code)] = {"supplier": supplier_address, "expires": int(self.clock()) + ttl_s}
            self.s.write(d)
        return code

    def redeem(self, code: str) -> Optional[str]:
        if not CODE_RX.match(code or ""):
            return None
        with self.s.lock:
            d = self.s.read()
            v = d.get(self._h(code))
            if not v or v.get("used") or v["expires"] <= self.clock():
                return None
            v["used"] = int(self.clock())
            self.s.write(d)
            return v["supplier"]


def parse_update(u: dict) -> Optional[Inbound]:
    """A private-chat text message, or None. Edits, groups, channels and media are not negotiation input."""
    m = u.get("message") if isinstance(u, dict) else None
    if not isinstance(m, dict) or (m.get("chat") or {}).get("type") != "private" or not isinstance(m.get("text"), str):
        return None
    chat = str(m["chat"]["id"])
    reply = str((m.get("reply_to_message") or {}).get("message_id", ""))
    return Inbound(f"{chat}:{m.get('message_id', '')}", f"tg:{chat}", int(m.get("date", 0) or 0), m["text"][:1000],
                   "text", f"tg:{chat}:{reply}" if reply else "")


class Poller:
    """Moves Telegram updates into the Gateway. run_once is one getUpdates round; start() runs it in a thread."""

    def __init__(self, gateway: Gateway, cfg: TgConfig, root: Path, name_of: Callable[[str], str],
                 call: Callable[..., dict] = _call, clock: Callable[[], float] = time.time):
        self.g, self.cfg, self.call, self.name_of = gateway, cfg, call, name_of
        self.invites = Invites(root, clock)
        self.offset = JsonStore(Path(root) / "telegram_offset.json", {"offset": 0})
        self.stop = threading.Event()
        self.last_error = ""

    def _reply(self, chat: str, text: str) -> None:
        ok, _, err = self.g.tg.send(chat, text) if self.g.tg else (False, "", "no sender")
        self.g.log("telegram_system_reply", chat=f"tg:…{chat[-4:]}", ok=ok, error=err)

    def handle(self, m: Inbound) -> dict:
        text = m.text.strip()
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()  # "/start@TiwalaBot" in some clients
        if cmd == "/start" and arg.strip():
            addr = self.invites.redeem(arg.strip())
            if not addr:
                self._reply(m.wa_id, "This invite link is not valid or has expired. Ask the buyer for a new one.")
                self.g.log("telegram_bad_invite", chat=f"tg:…{m.wa_id[-4:]}")
                return {"status": "bad_invite"}
            if not self.g.seen.first_time(f"telegram:{m.id}"):
                return {"status": "duplicate"}
            old = self.g.contacts.get(addr)
            self.g.contacts.put(Contact(addr, m.wa_id, "telegram", opted_in_at=self.g.now(),
                                        opt_in_source="supplier pressed Start on a one-time Telegram invite",
                                        last_inbound_at=self.g.now(), last_inbound_ts=m.ts))
            self.g.log("telegram_bound", supplier=addr, replaced=bool(old and old.wa_id != m.wa_id))
            self._reply(m.wa_id, f"Linked as {self.name_of(addr)}. The buyer's agent will send offers here. Reply "
                                 "ACCEPT <code> to accept an offer, write a counteroffer in your own words, or send "
                                 "/stop to opt out.")
            return {"status": "bound", "supplier": addr}
        if cmd in ("/start", "/stop"):
            if cmd == "/start" and self.g.contacts.get_by_wa(m.wa_id) is None:
                self._reply(m.wa_id, "Hello. This bot negotiates purchase orders for one buyer. Ask the buyer for "
                                     "your invite link and open it here to connect.")
                return {"status": "not_invited"}
            text = cmd[1:]
        elif cmd == "/help":
            text = "talk to a person" if self.g.contacts.get_by_wa(m.wa_id) else text
        return self.g.handle(Inbound(m.id, m.wa_id, m.ts, text, m.kind, m.context_id), "telegram")

    def run_once(self) -> int:
        with self.offset.lock:
            off = int(self.offset.read().get("offset", 0))
        ups = self.call(self.cfg.token, "getUpdates", {"offset": off, "timeout": POLL_TIMEOUT_S,
                                                       "allowed_updates": ["message"]}, POLL_TIMEOUT_S + 10) or []
        for u in ups:
            # Advance first: a message that crashes the handler is skipped, not retried forever.
            self.offset.write({"offset": int(u.get("update_id", 0)) + 1})
            m = parse_update(u)
            if m is None:
                continue
            try:
                self.handle(m)
            except Exception as e:
                self.g.log("telegram_error", error=_clean(e, self.cfg.token))
        return len(ups)

    def run(self) -> None:
        wait = 2
        while not self.stop.is_set():
            try:
                self.run_once()
                self.last_error, wait = "", 2
            except Exception as e:  # network down, bad token, or a webhook is set (409): back off, keep trying
                self.last_error = _clean(e, self.cfg.token)
                print(f"telegram: {self.last_error}; retrying in {wait}s", flush=True)
                self.stop.wait(wait)
                wait = min(wait * 2, 60)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="telegram-poller", daemon=True)
        t.start()
        return t

    def invite_link(self, supplier_address: str) -> str:
        user = self.cfg.username or (self.call(self.cfg.token, "getMe", {}) or {}).get("username", "")
        if not user:
            raise ValueError("Bot username unknown: set TELEGRAM_BOT_USERNAME or TELEGRAM_BOT_TOKEN.")
        return f"https://t.me/{user}?start={self.invites.create(supplier_address)}"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Owner-only: make a one-time Telegram invite link for a saved payee.")
    ap.add_argument("cmd", choices=["invite"])
    ap.add_argument("supplier", help="saved payee name")
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "agent"))
    from console.server import _load_env
    from .data import load_directory
    _load_env()
    cfg = TgConfig.from_env()
    data = Path(os.environ.get("TIWALA_DATA", str(root / "agent" / "data")))
    hits = [(addr, e) for addr, e in load_directory(data / "suppliers.json").items()
            if e.name.lower() == a.supplier.lower()]
    if len(hits) != 1:
        print(f"No single saved payee named {a.supplier!r}.")
        return 1
    if not cfg.token and not cfg.username:
        print("Set TELEGRAM_BOT_TOKEN in .env first.")
        return 1
    neg = data / "negotiation" / "whatsapp"
    g = Gateway(neg, Config(), None, lambda _a: None, lambda *_: None, lambda *_a, **_k: None)
    link = Poller(g, cfg, neg, lambda _a: "").invite_link(hits[0][0])
    print(f"One-time link for {hits[0][1].name} (valid 7 days, single use):\n{link}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
