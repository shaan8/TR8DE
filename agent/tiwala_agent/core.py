"""Orchestrator: input guard -> Coordinator -> intent verifier -> Checker -> policy engine
-> (confirmation) -> executor. Plus the monitor tick and owner commands.

Security properties enforced here in code, not in prompts:
  * The Coordinator's tools can only DRAFT. Execution needs an Authorization minted by the
    Gate after the policy engine allowed the action; the executor verifies its MAC.
  * Confirmation is matched deterministically on the owner's own next message. A model,
    the monitor, or contract text cannot confirm.
  * Owner-tier actions (attest, approve, dispute, resolve) run only from typed slash commands.
  * A new payee is saved only after the payee checks pass, the owner types "yes" plus the address's last
    4 characters, and the owner key signs addSupplier. The agent key cannot add payees.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from statistics import median
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from web3 import Web3

from . import forecast as fc
from .agents import COORDINATOR_SYSTEM, COORDINATOR_TOOLS, checker_review, treasury_plan
from .audit import AuditLog
from .chain import Chain, OwnerConsole
from .data import Plans, load_blocklist, load_directory, load_plans, save_directory
from .guard import as_data, tag_contract, tag_user
from .intent import parse as parse_intent, verify as verify_intent
from .llm import LLM
from .models import (MONEY_MOVING, PHP, Action, ActionKind, Deal, Origin, Outcome, Status, SupplierEntry, Tier,
                     Verdict, php)
from .payee import PayeeVerdict, check_payee, chunk
from .policy import PolicyContext, PolicySettings, decide
from .reputation import DpPolicy, dp_cap, score

def user_tz() -> tzinfo:
    """The owner's timezone: TIWALA_TZ (IANA name), else this device's zone, so deadlines read as local time."""
    for name in (os.environ.get("TIWALA_TZ"), os.environ.get("TZ")):
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
    try:
        real = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in real:
            return ZoneInfo(real.split("zoneinfo/", 1)[1])
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    return datetime.now().astimezone().tzinfo or timezone.utc
CONFIRM_RX = re.compile(r"^\s*(yes|y|confirm(ed)?|ok(ay)?|go( ahead)?|proceed|sige|oo)\s*[.!]*\s*$", re.I)
GUIDE = "\n".join([
    '**What Tiwala does**',
    'Pays your suppliers through on-chain escrow. The full PO is locked when a deal is created, the down payment goes out right after, and the balance only after you confirm delivery. Every new deal comes back to you for a yes.',
    '',
    '**Try asking**',
    "- What's my balance and what deals are open?",
    "- What is Lumen Textiles' delivery record?",
    '- Can I afford a PHP 80,000 PO on 2026-10-30?',
    '- Create escrow for Lumen PO-106, PHP 100,000, 20% down, delivery by 2026-10-30',
    '- Release the down payment for deal 6',
    '- Release the balance for deal 6 (after you /attest it)',
    '- Cancel deal 5 (only once it is overdue)',
    '- Save a new supplier, Kalinaw Crafts, payout 0x... (the address you got from the supplier)',
    '',
    '**Answering a confirmation card**',
    '- yes: confirm the deal on the card',
    '- Tell me what to change, for example "make it 15% down", and I re-check everything',
    '- Saving a payee: yes plus the last 4 characters of the address, for example "yes 1a2b"',
    '',
    '**Your own commands (signed with your key, never by the agent)**',
    '- /attest N: confirm delivery of deal N, which releases its balance',
    '- /approve N: approve a deal above your approval threshold',
    '- /dispute N: freeze deal N',
    '- /resolve N release or /resolve N refund: settle a dispute',
    '- /freeze: stop the agent and pause the wallet on-chain; /unfreeze to resume',
    '- /anchor: record the audit log head on Sepolia so deleting entries is detectable',
    '- Run monitor: check deadlines, attestations and balances now',
    '- /guide: show this list',
    '',
    '**Negotiations tab**',
    'Tiwala negotiates quantity, price, deposit and delivery with a supplier on WhatsApp or with their agent, inside your limits, then brings the exact agreement back here for your yes.',
    '',
    '**Built-in safety**',
    "Only saved payees can be paid, and new ones wait 24 hours. PO notes and supplier messages are treated as data, never instructions. Contract limits cap every deal and the agent's daily spend.",
])
PAYEE_CONFIRM_RX = re.compile(r"^\s*(yes|y|confirm|oo|sige)\s+([0-9a-f]{4})\s*[.!]*\s*$", re.I)
PENDING_TTL_S = 600
BREAKER_REFUSALS, BREAKER_WINDOW_S = 3, 600  # refused payment requests from chat before the agent freezes itself
MAX_TOOL_STEPS = 8


def _date(ts: int) -> str:
    return datetime.fromtimestamp(ts, user_tz()).strftime("%Y-%m-%d")


def _when(ts: int) -> str:
    """A deadline as the owner would write it: date only when it is end of day, else date, time and zone."""
    d = datetime.fromtimestamp(ts, user_tz())
    return d.strftime("%Y-%m-%d") if (d.hour, d.minute) == (23, 59) else d.strftime("%Y-%m-%d %H:%M UTC") + d.strftime("%z")[:3] + ":" + d.strftime("%z")[3:]


def _parse_deadline(s: str) -> int:
    """'YYYY-MM-DD' means 23:59 that day; 'YYYY-MM-DD HH:MM' (or with 'T') is that minute. Both in user_tz()."""
    s = s.strip().replace("T", " ")
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if not m:
        raise ValueError(f"deadline must be YYYY-MM-DD or YYYY-MM-DD HH:MM, got {s!r}")
    d = datetime.strptime(m.group(1), "%Y-%m-%d")
    hh, mm = (int(m.group(2)), int(m.group(3))) if m.group(2) else (23, 59)
    return int(d.replace(hour=hh, minute=mm, tzinfo=user_tz()).timestamp())


# ---------------------------------------------------------------------- gate


@dataclass(frozen=True)
class Authorization:
    digest: str
    tier: int
    expires: float
    mac: str
    nonce: str = ""


class Gate:
    """Mints and checks authorizations. The secret never leaves this object. Each authorization is single-use."""

    def __init__(self):
        self._key = secrets.token_bytes(32)
        self._used: dict[str, float] = {}  # nonce -> expiry, pruned as they lapse

    @staticmethod
    def digest(action: Action) -> str:
        return hashlib.sha256(json.dumps(action.to_dict(), sort_keys=True, default=str).encode()).hexdigest()

    def mint(self, action: Action, verdict: Verdict, confirmed: bool) -> Authorization:
        if not verdict.allowed:
            raise PermissionError("policy refused")
        if verdict.needs_confirmation and not confirmed:
            raise PermissionError("needs owner confirmation")
        dg, exp, nonce = self.digest(action), time.time() + 60, secrets.token_hex(16)
        mac = hmac.new(self._key, f"{dg}|{int(verdict.tier)}|{exp}|{nonce}".encode(), "sha256").hexdigest()
        return Authorization(dg, int(verdict.tier), exp, mac, nonce)

    def check(self, action: Action, auth: Optional[Authorization]) -> bool:
        if auth is None or time.time() > auth.expires or auth.digest != self.digest(action) or auth.nonce in self._used:
            return False
        want = hmac.new(self._key, f"{auth.digest}|{auth.tier}|{auth.expires}|{auth.nonce}".encode(), "sha256").hexdigest()
        return hmac.compare_digest(want, auth.mac)

    def consume(self, action: Action, auth: Optional[Authorization]) -> bool:
        """check() and mark the authorization used, so it can sign at most one transaction."""
        if not self.check(action, auth):
            return False
        now = time.time()
        self._used = {n: e for n, e in self._used.items() if e > now}
        self._used[auth.nonce] = auth.expires
        return True


class Executor:
    def __init__(self, chain: Chain, wallet: str, gate: Gate):
        self.chain, self.wallet, self.gate = chain, wallet, gate

    def execute(self, action: Action, auth: Optional[Authorization]):
        if not self.gate.consume(action, auth):
            raise PermissionError("executor: missing, invalid or already used authorization")
        return self.chain.send(self.wallet, action)


# ---------------------------------------------------------------------- orchestrator


@dataclass
class Pending:
    action: Action
    request: str
    texts: list[str]
    checker: tuple[bool, str]
    card: str
    created: float
    then_release_down: bool = False


@dataclass
class PendingPayee:
    verdict: PayeeVerdict
    texts: list[str]  # the owner's words the address came from
    untrusted: list[str]
    card: str
    created: float


@dataclass
class TurnResult:
    reply: str
    events: list[dict] = field(default_factory=list)


class Tiwala:
    def __init__(
        self,
        chain: Chain,
        wallet: str,
        data_dir: str | Path,
        llms: dict[str, LLM],
        audit: AuditLog,
        owner: Optional[OwnerConsole] = None,
        settings: PolicySettings = PolicySettings(),
        dp: DpPolicy = DpPolicy(),
    ):
        self.chain, self.wallet = chain, Web3.to_checksum_address(wallet)
        self.data = Path(data_dir)
        self.llms, self.audit, self.owner = llms, audit, owner
        self.settings, self.dp = settings, dp
        self.gate = Gate()
        self.executor = Executor(chain, self.wallet, self.gate)
        self.history: list[dict] = []
        self.ledger: list[str] = []  # owner's own words for the current draft
        self.pending: Optional[Pending] = None
        self.pending_payee: Optional[PendingPayee] = None
        self.pending_negotiation: Optional[dict] = None  # {"spec", "card", "created"}
        self.negotiations = None  # NegotiationService, attached by the service itself
        self._contract_texts: set[str] = set()
        self._events: list[dict] = []
        self.agreements: dict[str, dict] = {}  # Origin.detail -> agreed fields, registered by propose_negotiated
        self.on_executed: list = []  # callbacks(action, result) after an owner-confirmed action executes

    # ------------------------------------------------------------ data

    @property
    def directory(self):
        return load_directory(self.data / "suppliers.json")

    def names(self) -> dict[str, str]:
        return {a: e.name for a, e in self.directory.items()}

    def plans(self) -> Plans:
        return load_plans(self.data / "plans.json")

    def _supplier_by_name(self, name: str) -> Optional[str]:
        n = (name or "").strip().lower()
        if not n:
            return None
        if Web3.is_address(n):
            return Web3.to_checksum_address(n)
        for addr, e in self.directory.items():
            if e.name.lower() == n or e.name.lower().split()[0] == n.split()[0]:
                return addr
        return None

    def _log(self, event: str, **data) -> None:
        e = self.audit.write(event, **data)
        self._events.append({"event": event, **data, "ts": e["ts"], "line": self.audit.count})

    # ------------------------------------------------------------ context

    def _context(self, action: Action) -> tuple[PolicyContext, Optional[Deal]]:
        ws = self.chain.wallet_state(self.wallet)
        deal = self.chain.deal(self.wallet, action.deal_id) if action.deal_id else None
        supplier = action.supplier or (deal.supplier if deal else None)
        listed, active = {}, {}
        if supplier:
            listed[supplier], active[supplier] = self.chain.supplier_onchain(self.wallet, supplier)
        closed = self.chain.closed_deals()
        rep = score(closed, supplier) if supplier else None
        policy = DpPolicy(self.dp.dp_min_bps, self.dp.dp_max_bps, self.dp.stranger_cap_bps, ws.max_down_bps)
        cap = dp_cap(rep, self.wallet, closed, policy) if rep else None
        mine = [c.total for c in closed if c.buyer == self.wallet and c.outcome != Outcome.NEUTRAL]
        open_exp = sum(d.unpaid for d in self.chain.deals(self.wallet) if d.supplier == supplier)
        short = None
        if action.kind == ActionKind.CREATE_DEAL and action.total:
            p, today = self.plans(), ws.now // 86400
            f = fc.with_new_deal(ws.free, p.inflows, p.planned,
                                 p.buffer, today, action.total, today)
            if not f.ok:
                short = (f.shortfall_day, f.shortfall)
        ctx = PolicyContext(
            wallet=ws, directory=self.directory, onchain_listed=listed, onchain_active_at=active,
            blocklist=load_blocklist(self.data / "blocklist.json"), deal=deal, reputation=rep, cap=cap,
            buyer_median=int(median(mine)) if mine else None, open_exposure=open_exp, forecast_shortfall=short,
        )
        return ctx, deal

    def _action_view(self, a: Action, ctx: PolicyContext, deal: Optional[Deal]) -> dict:
        names = self.names()
        sup = a.supplier or (deal.supplier if deal else None)
        total = a.total if a.total is not None else (deal.total if deal else None)
        bps = a.down_bps if a.down_bps is not None else (deal.down_bps if deal else None)
        v = {"kind": a.kind.value, "supplier": names.get(sup, f"unregistered address {sup}")}
        if a.deal_id:
            v["deal_id"] = a.deal_id
        if total is not None:
            v["total_php"] = total / PHP
        if bps is not None and total is not None:
            v["down_payment_pct"] = bps / 100
            v["down_payment_php"] = total * bps // 10_000 / PHP
            v["balance_php"] = (total - total * bps // 10_000) / PHP
        if a.kind == ActionKind.CREATE_DEAL:
            v["po_ref"] = a.ref
            v["deliver_by"] = _when(a.deadline) if a.deadline else None
        facts = {}
        if ctx.cap:
            facts["supplier_down_payment_cap_pct"] = ctx.cap.cap_bps / 100
        if deal:
            facts["deal_status"] = deal.status.name
        v["facts"] = facts
        return v

    def _request_desc(self, a: Action, deal: Optional[Deal], system_note: str = "") -> str:
        if a.origin.kind == "user":
            said = "\n".join(f'Owner said: "{t}"' for t in self.ledger[-6:]) or "(no request)"
            named = parse_intent(self.ledger[-6:], list(self.names().values())).suppliers
            if named:  # short names ("Bayani") resolved in code, so the Checker does not refuse them
                said += "\nSystem (not the owner): saved payees named in the owner's words: " + ", ".join(named)
            return said + (f"\nSystem (not the owner): {system_note}" if system_note else "")
        if a.origin.kind == "negotiation":
            base = self.agreements.get(a.origin.detail, {}).get("summary", "Negotiated agreement (no summary on record)")
            return base + (f"\nSystem (not the owner): {system_note}" if system_note else "")
        rule, _ = a.origin.detail.split(":", 1)
        if rule == "overdue_cancel" and deal:
            return (f"Monitor rule overdue_cancel fired for deal {deal.id}: deadline {_when(deal.deadline)} plus grace "
                    f"has passed with no delivery attestation and no dispute. The rule cancels the deal and refunds "
                    f"the unpaid escrow to the wallet.")
        if rule == "attested_release" and deal:
            return (f"Monitor rule attested_release fired for deal {deal.id}: the owner signed the delivery "
                    f"attestation on-chain. The rule releases the remaining balance to the deal's supplier.")
        return f"Monitor rule {a.origin.detail}"

    # ------------------------------------------------------------ pipeline

    def _intent(self, a: Action, texts: list[str], deal):
        if a.origin.kind == "user":
            return verify_intent(a, texts, self.names(), deal)
        return verify_intent(a, [], {}, deal, self.agreements.get(a.origin.detail))

    # ------------------------------------------------------------ circuit breaker

    def frozen(self) -> Optional[dict]:
        p = self.data / "frozen.json"
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except (OSError, ValueError):
            return {"reason": "freeze file unreadable; treated as frozen"}  # fail closed

    def _freeze(self, reason: str) -> None:
        (self.data / "frozen.json").write_text(json.dumps({"reason": reason, "at": int(time.time())}))
        self._log("agent_frozen", reason=reason)

    def _note_refusal(self, a: Action) -> Optional[str]:
        """Repeated refused payment requests from chat look like an attack or a confused model: stop the agent."""
        now = time.time()
        self._refusals = [t for t in getattr(self, "_refusals", []) if now - t < BREAKER_WINDOW_S] + [now]
        if len(self._refusals) >= BREAKER_REFUSALS and not self.frozen():
            self._freeze(f"{len(self._refusals)} refused payment requests within {BREAKER_WINDOW_S // 60} minutes")
            return "Circuit breaker tripped: the agent is now frozen until the owner types /unfreeze."
        return None

    def propose(self, a: Action, then_release_down: bool = False, system_note: str = "") -> dict:
        if (f := self.frozen()) and a.kind in MONEY_MOVING:
            return {"status": "refused", "reasons": [f"The agent is frozen ({f['reason']}). Type /unfreeze to resume."]}
        ctx, deal = self._context(a)
        intent = self._intent(a, self.ledger[-6:], deal)
        ctx.intent_mismatches = intent.mismatches
        view = self._action_view(a, ctx, deal)
        request = self._request_desc(a, deal, system_note)
        ok, reason = checker_review(self.llms["checker"], request, view)
        ctx.checker_approved, ctx.checker_reason = ok, reason
        verdict = decide(a, ctx, self.settings)
        self._log("verdict", action=a.to_dict(), view=view, intent=intent.__dict__,
                  checker={"approve": ok, "reason": reason}, verdict=verdict.to_dict())
        if not verdict.allowed:
            out = {"status": "refused", "reasons": verdict.reasons, "flags": verdict.flags}
            if a.origin.kind == "user" and (b := self._note_refusal(a)):
                out["reasons"] = out["reasons"] + [b]
            return out
        if verdict.needs_confirmation:
            card = self._card(a, ctx, deal, verdict, intent.agent_filled, then_release_down)
            self.pending = Pending(a, request, list(self.ledger), (ok, reason), card, time.time(), then_release_down)
            return {"status": "needs_confirmation", "card": card, "flags": verdict.flags}
        return self._execute(a, verdict, confirmed=False)

    def _execute(self, a: Action, verdict: Verdict, confirmed: bool) -> dict:
        auth = self.gate.mint(a, verdict, confirmed)
        res = self.executor.execute(a, auth)
        if not res.ok:
            self._log("tx_failed", action=a.to_dict(), error=res.error, tx=res.tx_hash)
            return {"status": "failed", "error": res.error, "tx": res.tx_hash}
        out = {"status": "executed", "tx": res.tx_hash, "tier": int(verdict.tier)}
        if a.kind == ActionKind.CREATE_DEAL:
            out["deal_id"] = self.chain.deal_id_from_receipt(self.wallet, res.tx_hash)
        self._log("executed", action=a.to_dict(), tx=res.tx_hash, block=res.block, **{k: v for k, v in out.items() if k == "deal_id"})
        return out

    def confirm_pending(self) -> dict:
        p = self.pending
        self.pending = None
        if p is None:
            return {"status": "none"}
        if time.time() - p.created > PENDING_TTL_S:
            return {"status": "expired"}
        saved = self.ledger
        self.ledger = p.texts
        try:
            ctx, deal = self._context(p.action)  # fresh chain state at confirmation time
            intent = self._intent(p.action, p.texts[-6:], deal)
            ctx.intent_mismatches = intent.mismatches
            ctx.checker_approved, ctx.checker_reason = p.checker
            verdict = decide(p.action, ctx, self.settings)
            self._log("confirmed", action=p.action.to_dict(), verdict=verdict.to_dict())
            if not verdict.allowed:
                return {"status": "refused", "reasons": verdict.reasons}
            out = self._execute(p.action, verdict, confirmed=True)
            if out["status"] == "executed" and p.then_release_down and out.get("deal_id"):
                rel = Action(ActionKind.RELEASE_DOWN, p.action.origin, deal_id=out["deal_id"])
                c = p.action
                note = (f"the owner replied yes to a confirmation card for {c.ref or 'this PO'} that said "
                        f"\"Down payment: {c.down_bps / 100:g}% = {php(c.total * c.down_bps // 10_000)}, released right "
                        f"after creation\". That deal is now deal {out['deal_id']}; this action is that release.")
                out["down_payment"] = self.propose(rel, system_note=note)
            if out["status"] == "executed":
                for cb in self.on_executed:
                    cb(p.action, out)
            return out
        finally:
            self.ledger = saved

    # ------------------------------------------------------------ rendering

    def _card(self, a: Action, ctx: PolicyContext, deal, v: Verdict, filled: list[str], then_down: bool) -> str:
        names = self.names()
        lines = []
        if a.kind == ActionKind.CREATE_DEAL:
            down = a.total * a.down_bps // 10_000
            lines += [
                "CONFIRM NEW ESCROW DEAL",
                f"Supplier: {names.get(a.supplier, a.supplier)}" + (f" ({ctx.reputation.summary()})" if ctx.reputation else ""),
                f"PO: {a.ref}   Locked now: {php(a.total)} (full PO)",
                f"Down payment: {a.down_bps / 100:g}% = {php(down)}" + (", released right after creation" if then_down else ""),
                (f"Cap: {ctx.cap.cap_bps / 100:g}% (network {ctx.cap.network_cap_bps / 100:g}%"
                 + ((f", new to you so the {self.dp.stranger_cap_bps / 100:g}% stranger cap applies"
                     if ctx.cap.cap_bps < ctx.cap.network_cap_bps else
                     f", new to you; the {self.dp.stranger_cap_bps / 100:g}% stranger cap does not bind")
                    if ctx.cap.stranger else "")
                 + ")") if ctx.cap else "",
                f"Balance {php(a.total - down)} only after your delivery attestation (/attest)",
                f"Deliver by: {_when(a.deadline)}",
            ]
            if ctx.forecast_shortfall:
                lines.append(f"Forecast: short by {php(ctx.forecast_shortfall[1])} on {_date(ctx.forecast_shortfall[0] * 86400)}")
            else:
                lines.append("Forecast: no shortfall")
        else:
            lines += [f"CONFIRM {a.kind.value.replace('_', ' ').upper()} for deal {a.deal_id}",
                      f"Supplier: {names.get(deal.supplier, deal.supplier) if deal else '?'}"]
        if a.origin.kind == "negotiation":
            ag = self.agreements.get(a.origin.detail, {})
            lines.append(f"From negotiation {ag.get('label', a.origin.detail)}; supplier accepted these exact terms "
                         f"({ag.get('supplier_via', 'unknown channel')}). Your yes is the payment approval.")
        if v.flags:
            lines.append("Risk flags: " + ", ".join(v.flags))
        if filled:
            lines.append("Filled in by Tiwala, please check: " + ", ".join(filled))
        lines += [r for r in v.reasons if r]
        lines.append('Reply "yes" to confirm, or tell me what to change.')
        return "\n".join(l for l in lines if l)

    # ------------------------------------------------------------ chat

    def handle(self, text: str) -> TurnResult:
        self._events = []
        t = tag_user(text)
        self._log("user_message", text=t.text, flags=list(t.flags))

        if t.text.strip().lower() in ("/guide", "/help", "help"):
            return TurnResult(GUIDE, self._events)
        if t.text.strip().startswith("/"):
            return TurnResult(self._owner_command(t.text.strip()), self._events)

        if self.pending_payee:
            if m := PAYEE_CONFIRM_RX.match(t.text):
                return TurnResult(self._confirm_payee(m.group(2)), self._events)
            if CONFIRM_RX.match(t.text):
                return TurnResult('To save a payee, reply "yes" and the last 4 characters of the address, for '
                                  'example "yes 1a2b". Reading them off the card is the check.', self._events)
            self._log("payee_dropped", address=self.pending_payee.verdict.address)
            self.pending_payee = None

        if self.pending_negotiation:
            p, self.pending_negotiation = self.pending_negotiation, None
            if CONFIRM_RX.match(t.text):
                return TurnResult(self._start_negotiation(p), self._events)
            self._log("negotiation_draft_dropped", supplier=p["spec"]["supplier"])

        if self.pending and CONFIRM_RX.match(t.text):
            out = self.confirm_pending()
            self.ledger = []
            return TurnResult(self._render_result(out), self._events)
        if self.pending:
            self._log("pending_dropped", action=self.pending.action.to_dict())
            self.pending = None

        self.ledger.append(t.text)
        self._contract_texts = set()
        note = f"\n\n[input guard: flags={','.join(t.flags)}]" if t.flags else ""
        turn_start = len(self.history)
        self.history.append({"role": "user", "content": t.text + note})
        cards: list[str] = []
        reply = ""
        for _ in range(MAX_TOOL_STEPS):
            try:
                r = self.llms["coordinator"].complete(COORDINATOR_SYSTEM, self.history, COORDINATOR_TOOLS)
            except Exception as e:  # model down or rate-limited: nothing was drafted, so drop the turn
                del self.history[turn_start:]
                self._log("coordinator_error", error=f"{type(e).__name__}: {str(e)[:200]}")
                return TurnResult(f"The assistant model is unavailable right now ({type(e).__name__}). "
                                  "Nothing was drafted or sent; please try again.", self._events)
            blocks = ([{"type": "text", "text": r.text}] if r.text else []) + [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in r.tool_calls]
            self.history.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "..."}]})
            if not r.tool_calls:
                reply = r.text
                break
            results = []
            for c in r.tool_calls:
                self._log("tool_call", name=c.name, args=c.args)
                try:
                    res = self._tool(c.name, c.args)
                except Exception as e:  # report, never retry money-moving calls silently
                    res = {"status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
                if isinstance(res, dict) and res.get("card"):
                    cards.append(res["card"])
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(res, default=str)})
            self.history.append({"role": "user", "content": results})
        else:
            reply = "I could not finish that safely in one go. Nothing was paid. Could you say it more simply?"
        if any(e["event"] == "executed" for e in self._events):
            self.ledger = []
        if any(e["event"] == "agent_frozen" for e in self._events):  # shown by code, not left to the model
            cards.append("Circuit breaker: I have frozen myself after repeated refused payment requests. Nothing "
                         "moves until you type /unfreeze. Type /freeze to also pause the wallet on-chain.")
        return TurnResult("\n\n".join([reply] + cards).strip(), self._events)

    def _render_result(self, out: dict) -> str:
        s = out.get("status")
        if s == "executed":
            msg = f"Done. Tx {out['tx']}" + (f" (deal {out['deal_id']})" if out.get("deal_id") else "")
            dp = out.get("down_payment")
            if dp:
                msg += "\n" + ("Down payment released. Tx " + dp["tx"] if dp.get("status") == "executed"
                               else "Down payment not released: " + "; ".join(dp.get("reasons", [dp.get("error", "")])))
            return msg
        if s == "refused":
            return "I did not execute it. " + " ".join(out["reasons"])
        if s == "failed":
            return f"The transaction did not go through ({out['error']}). Nothing was retried."
        if s == "expired":
            return "That confirmation expired. Ask again and I will re-check everything."
        return "There is nothing waiting for confirmation."

    # ------------------------------------------------------------ tools

    def _origin(self, fields: list[str]) -> Origin:
        user = " ".join(self.ledger).lower()
        from_ct = any(f and f.lower() not in user and any(f.lower() in ct.lower() for ct in self._contract_texts)
                      for f in fields)
        return Origin("user", self.ledger[-1] if self.ledger else "", from_contract_text=from_ct)

    def _tool(self, name: str, a: dict):
        if name == "get_overview":
            ws = self.chain.wallet_state(self.wallet)
            names = self.names()
            deals = []
            for d in self.chain.deals(self.wallet):
                if d.status in (Status.COMPLETED, Status.REFUNDED):
                    continue
                ref = tag_contract(d.ref)
                self._contract_texts.add(d.ref)
                deals.append({"deal_id": d.id, "supplier": names.get(d.supplier, d.supplier), "status": d.status.name,
                              "total_php": d.total / PHP, "down_pct": d.down_bps / 100, "deliver_by": _when(d.deadline),
                              "po_ref": as_data(ref, f"contract:deal{d.id}.ref")})
            return {"free_php": ws.free / PHP, "locked_php": ws.locked / PHP, "underfunded": ws.underfunded,
                    "paused": ws.paused, "agent_daily_remaining_php": ws.daily_remaining / PHP,
                    "open_deals": deals}
        if name == "get_supplier":
            addr = self._supplier_by_name(a.get("name", ""))
            if not addr or addr not in self.directory:
                return {"error": "not a registered supplier"}
            closed = self.chain.closed_deals()
            rep = score(closed, addr)
            ws = self.chain.wallet_state(self.wallet)
            cap = dp_cap(rep, self.wallet, closed, DpPolicy(self.dp.dp_min_bps, self.dp.dp_max_bps,
                                                            self.dp.stranger_cap_bps, ws.max_down_bps))
            return {"supplier": self.directory[addr].name, "on_time": rep.on_time, "late": rep.late,
                    "non_delivery": rep.non_delivery, "buyers": rep.buyers, "effective_buyers": round(rep.k_eff, 2),
                    "score_R": round(rep.r, 2), "down_payment_cap_pct": cap.cap_bps / 100,
                    "new_to_you": cap.stranger, "explanation": cap.reason}
        if name == "forecast":
            ws = self.chain.wallet_state(self.wallet)
            p, today = self.plans(), ws.now // 86400
            total = round(float(a["total_php"]) * PHP)
            day = _parse_deadline(a["date"]) // 86400 if a.get("date") else today
            f = fc.with_new_deal(ws.free, p.inflows, p.planned, p.buffer, today, total, day)
            opts = [o.__dict__ for o in fc.options(ws.free, p.inflows, p.planned, p.buffer, today, total, day)]
            summary = {"ok": f.ok, "shortfall_php": f.shortfall / PHP,
                       "shortfall_date": _date(f.shortfall_day * 86400) if f.shortfall_day else None,
                       "free_php": ws.free / PHP, "buffer_php": p.buffer / PHP}
            plan = treasury_plan(self.llms.get("treasury"), summary, opts)
            return {**summary, "fixes": [opts[i] for i in plan["ranked"]], "treasury_note": plan["explanation"]}
        if name == "draft_create_deal":
            addr = self._supplier_by_name(a.get("supplier", ""))
            if addr is None:
                return {"status": "refused", "reasons": [f"'{a.get('supplier')}' is not a registered supplier."]}
            act = Action(ActionKind.CREATE_DEAL, self._origin([addr, a.get("po_ref", "")]), supplier=addr,
                         total=round(float(a["total_php"]) * PHP), down_bps=round(float(a["down_pct"]) * 100),
                         deadline=_parse_deadline(a["deadline"]), ref=str(a.get("po_ref", ""))[:64])
            return self.propose(act, then_release_down=True)
        if name == "draft_negotiation":
            return self.propose_negotiation(a)
        if name == "draft_save_supplier":
            return self.propose_payee(str(a.get("name", "")), str(a.get("address", "")))
        kinds = {"draft_release_down_payment": ActionKind.RELEASE_DOWN,
                 "draft_release_balance": ActionKind.RELEASE_BALANCE, "draft_cancel": ActionKind.CANCEL}
        if name in kinds:
            return self.propose(Action(kinds[name], self._origin([]), deal_id=int(a["deal_id"])))
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------ negotiated deals

    def propose_negotiation(self, a: dict) -> dict:
        """Owner asked in chat to negotiate. Checked in code, shown as a card, opened only on the owner's own yes."""
        if self.negotiations is None:
            return {"status": "refused", "reasons": ["Negotiations are not available here; use the Negotiations tab."]}
        addr = self._supplier_by_name(str(a.get("supplier", "")))
        if addr is None:
            return {"status": "refused", "reasons": [f"'{a.get('supplier')}' is not a saved payee. Save it first."]}
        name = self.directory[addr].name
        if name not in parse_intent(self.ledger[-6:], list(self.names().values())).suppliers:
            return {"status": "refused", "reasons": [f"You did not name {name}; say which supplier to negotiate with."]}
        try:
            qty, price = int(a["quantity"]), float(a["target_unit_price_php"])
            spec = {"supplier": name, "product": str(a["product"])[:80], "desired_qty": qty,
                    "min_qty": int(a.get("min_quantity") or qty), "target_unit_price_php": price,
                    "max_total_php": float(a["max_total_php"]), "min_reserve_php": float(a.get("keep_free_php") or 0),
                    "latest_delivery": str(a["latest_delivery"]),
                    "preferred_delivery": str(a.get("preferred_delivery") or a["latest_delivery"]),
                    "opening_deposit_pct": float(a.get("opening_deposit_pct") or 10)}
            _parse_deadline(spec["latest_delivery"]), _parse_deadline(spec["preferred_delivery"])
        except (KeyError, ValueError, TypeError) as e:
            return {"status": "refused", "reasons": [f"Missing or unreadable value ({e}); ask the owner for it."]}
        channel = self.negotiations.chat_channel(addr)
        if channel is None:
            return {"status": "refused", "reasons": [f"{name} has no WhatsApp contact and no supplier agent."]}
        card = "\n".join([
            "CONFIRM NEGOTIATION",
            f"Supplier: {name}   Channel: {channel}",
            f"Product: {spec['product']}",
            f"Opening offer: {qty:,} at {php(round(price * PHP))} each, {spec['opening_deposit_pct']:g}% deposit, "
            f"delivery {spec['preferred_delivery']}",
            f"Your private limits: at least {spec['min_qty']:,} units, at most {php(round(spec['max_total_php'] * PHP))} "
            f"total, delivery by {spec['latest_delivery']}, keep {php(round(spec['min_reserve_php'] * PHP))} free",
            "The supplier never sees your limits. No money moves: an agreed deal comes back here for your yes.",
            'Reply "yes" to send the opening offer.'])
        self.pending_negotiation = {"spec": spec, "card": card, "created": time.time()}
        self._log("negotiation_drafted", supplier=name, channel=channel)
        return {"status": "needs_confirmation", "card": card}

    def _start_negotiation(self, p: dict) -> str:
        if time.time() - p["created"] > PENDING_TTL_S:
            return "That confirmation expired. Ask again and I will draft it fresh."
        try:
            n = self.negotiations.start_from_chat(p["spec"])
        except Exception as e:
            return f"I could not open the negotiation: {e}"
        self._log("negotiation_opened_from_chat", negotiation=n["id"])
        sent = n.get("sent") or ""
        return (f"Opened negotiation NEG-{n['id']} with {p['spec']['supplier']} ({n['channel_label']}). {sent}"
                " Follow it in the Negotiations tab.").replace("  ", " ")

    def propose_negotiated(self, detail: str, supplier: str, total: int, down_bps: int, deadline: int, ref: str,
                           summary: str, label: str, supplier_via: str) -> dict:
        """Draft the escrow for an agreed negotiation. Same pipeline as a chat request: intent (the action must equal
        the agreement), Checker, policy, then a confirmation card the owner answers in their own words."""
        if self.pending:
            self._log("pending_dropped", action=self.pending.action.to_dict())
            self.pending = None
        self.pending_payee = None
        self.agreements[detail] = {"supplier": supplier, "total": total, "down_bps": down_bps, "deadline": deadline,
                                   "ref": ref, "summary": summary, "label": label, "supplier_via": supplier_via}
        a = Action(ActionKind.CREATE_DEAL, Origin("negotiation", detail), supplier=supplier, total=total,
                   down_bps=down_bps, deadline=deadline, ref=ref)
        self._events = []
        self.ledger = []
        return self.propose(a, then_release_down=True)

    # ------------------------------------------------------------ payees

    def _reserved(self) -> dict[str, str]:
        ws = self.chain.wallet_state(self.wallet)
        return {"wallet": self.wallet, "owner": ws.owner, "agent": ws.agent,
                "settlement token": self.chain.token.address, "factory": self.chain.factory.address}

    def _payee_card(self, v: PayeeVerdict, delay_s: int) -> str:
        hours = f"{delay_s / 3600:g}-hour" if delay_s >= 3600 else f"{delay_s}-second"
        lines = ["CONFIRM PAYOUT ADDRESS CHANGE" if v.kind == "address_change" else "CONFIRM NEW PAYEE",
                 f"Name: {v.name}", f"Address: {chunk(v.address)}"]
        if v.replaces:
            lines.append(f"Replaces: {chunk(v.replaces)}")
        lines.append("Checks passed: " + ", ".join(c.rule for c in v.checks if c.ok))
        if v.flags:
            lines.append("Risk flags: " + ", ".join(v.flags))
        lines += [c.detail for c in v.checks if not c.ok]
        lines += [f"Signed with your owner key, not the agent's. Payable after the wallet's {hours} waiting period.",
                  'Reply "yes" and the last 4 characters of the address to save it.']
        return "\n".join(lines)

    def propose_payee(self, name: str, address: str) -> dict:
        if self.pending:
            self._log("pending_dropped", action=self.pending.action.to_dict())
            self.pending = None
        untrusted = sorted(self._contract_texts)
        v = check_payee(name, address, self.ledger[-6:], untrusted, self.directory,
                        load_blocklist(self.data / "blocklist.json"), self._reserved())
        out = v.to_dict()
        if not v.allowed:
            self._log("payee_check", **out)
            return {"status": "refused", "reasons": v.reasons, "flags": v.flags}
        delay = self.chain.supplier_delay(self.wallet)
        card = self._payee_card(v, delay)
        self._log("payee_check", **out, delay_s=delay)
        self.pending_payee = PendingPayee(v, list(self.ledger[-6:]), untrusted, card, time.time())
        return {"status": "needs_confirmation", "card": card, "flags": v.flags,
                "note": 'The owner must reply "yes" plus the last 4 characters of the address. Do not repeat them.'}

    def _confirm_payee(self, code: str) -> str:
        p, self.pending_payee = self.pending_payee, None
        self.ledger = []
        v = p.verdict
        if time.time() - p.created > PENDING_TTL_S:
            self._log("payee_confirm_failed", address=v.address, reason="expired")
            return "That confirmation expired. Ask again and I will re-check the address."
        if code.lower() != v.address[-4:].lower():
            self._log("payee_confirm_failed", address=v.address, reason="last 4 characters did not match")
            return (f"Those are not the last 4 characters of {chunk(v.address)}. Nothing was saved. "
                    "Ask again to start over.")
        fresh = check_payee(v.name, v.address, p.texts, p.untrusted, self.directory,
                            load_blocklist(self.data / "blocklist.json"), self._reserved())
        self._log("payee_confirmed", address=v.address, allowed=fresh.allowed, reasons=fresh.reasons)
        if not fresh.allowed:
            return "I did not save it. " + " ".join(fresh.reasons)
        if self.owner is None:
            return "Saving a payee needs the owner key configured on this device. Nothing was saved."
        r = self.owner.add_supplier(v.address)
        if not r.ok:
            self._log("payee_failed", address=v.address, error=r.error, tx=r.tx_hash)
            return f"The owner transaction did not go through ({r.error}). Nothing was saved."
        removed = self.owner.remove_supplier(v.replaces) if v.replaces else None
        _, active_at = self.chain.supplier_onchain(self.wallet, v.address)
        d = self.directory
        if v.replaces:
            d.pop(v.replaces, None)
        d[v.address] = SupplierEntry(v.name, v.address, self.chain.now() if v.replaces else 0)
        save_directory(self.data / "suppliers.json", d)
        self._log("payee_saved", name=v.name, address=v.address, kind=v.kind, replaces=v.replaces, tx=r.tx_hash,
                  block=r.block, active_at=active_at, remove_tx=removed.tx_hash if removed else None,
                  remove_ok=removed.ok if removed else None)
        msg = f"Saved {v.name} at {chunk(v.address)}. Signed by you. Tx {r.tx_hash}"
        if removed:
            msg += (f"\nOld address removed. Tx {removed.tx_hash}" if removed.ok else
                    f"\nThe old address could not be removed ({removed.error}). Run it again from the owner key.")
        return msg + f"\nPayable from {_when(active_at)}, after the wallet's waiting period."

    # ------------------------------------------------------------ owner commands

    def _owner_command(self, cmd: str) -> str:
        if self.owner is None:
            return "Owner commands need the owner key configured on this device."
        parts = cmd.split()
        op = parts[0].lower()
        if op in ("/freeze", "/unfreeze", "/anchor"):
            return self._safety_command(op)
        try:
            n = int(parts[1])
        except (IndexError, ValueError):
            return "Usage: /attest <deal>, /approve <deal>, /dispute <deal>, /resolve <deal> release|refund"
        if op == "/attest":
            r = self.owner.attest(n)
        elif op == "/approve":
            r = self.owner.approve(n)
        elif op == "/dispute":
            r = self.owner.dispute(n)
        elif op == "/resolve" and len(parts) > 2 and parts[2] in ("release", "refund"):
            r = self.owner.resolve(n, parts[2] == "release")
        else:
            return "Unknown owner command."
        self._log("owner_command", command=cmd, ok=r.ok, tx=r.tx_hash, error=r.error)
        if not r.ok:
            return f"Owner action failed: {r.error}"
        msg = f"Signed by you. Tx {r.tx_hash}"
        if op == "/attest":
            notes = self.tick()
            if notes:
                msg += "\n" + "\n".join(notes)
        return msg

    def anchor_audit(self) -> str:
        from .audit import anchor_payload
        count, head = self.audit.count, self.audit._prev
        if not count:
            return "The audit log is empty; nothing to anchor."
        r = self.owner.anchor(anchor_payload(count, head))
        if not r.ok:
            return f"Anchoring failed: {r.error}"
        rec = {"tx": r.tx_hash, "count": count, "head": head, "chain_id": self.chain.w3.eth.chain_id,
               "owner": self.owner.acct.address, "ts": int(time.time())}
        with (Path(self.audit.path).parent / "anchors.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self._log("audit_anchored", **rec)
        return (f"Audit log anchored on-chain at entry {count}. Signed by you. Tx {r.tx_hash}\n"
                "Deleting or rewriting any entry up to here is now detectable: scripts/verify_audit.py.")

    def _safety_command(self, op: str) -> str:
        if op == "/anchor":
            return self.anchor_audit()
        if op == "/freeze":
            if not self.frozen():
                self._freeze("frozen by the owner")
            r = self.owner.set_paused(True)
            self._log("owner_command", command=op, ok=r.ok, tx=r.tx_hash, error=r.error)
            return ("Agent frozen and wallet paused on-chain. Signed by you. Tx " + r.tx_hash if r.ok else
                    f"Agent frozen off-chain; the on-chain pause failed ({r.error}).")
        (self.data / "frozen.json").unlink(missing_ok=True)
        self._refusals = []
        self._log("agent_unfrozen")
        if not self.chain.wallet_state(self.wallet).paused:
            return "Agent unfrozen. The wallet was not paused."
        r = self.owner.set_paused(False)
        self._log("owner_command", command=op, ok=r.ok, tx=r.tx_hash, error=r.error)
        return ("Agent unfrozen and wallet unpaused. Signed by you. Tx " + r.tx_hash if r.ok else
                f"Agent unfrozen, but unpausing the wallet failed ({r.error}).")

    # ------------------------------------------------------------ monitor

    def tick(self) -> list[str]:
        ws = self.chain.wallet_state(self.wallet)
        if ws.underfunded:
            self._log("monitor_halt", reason="isUnderfunded", balance=ws.balance, locked=ws.locked)
            return [f"HALTED: escrow holds {php(ws.balance)} but open deals need {php(ws.locked)} "
                    "(likely an issuer clawback). I will not move any funds until this is resolved."]
        notes = []
        names = self.names()
        for d in self.chain.deals(self.wallet):
            who = names.get(d.supplier, d.supplier)
            overdue = ws.now > d.deadline + ws.grace
            if d.status in (Status.LOCKED, Status.DOWN_PAID) and overdue:
                out = self.propose(Action(ActionKind.CANCEL, Origin("monitor", f"overdue_cancel:{d.id}"), deal_id=d.id))
                notes.append(self._monitor_note(f"Deal {d.id} with {who} is overdue", out))
            elif d.status == Status.DISPUTED and overdue:
                notes.append(f"Deal {d.id} with {who} is overdue but disputed; waiting for you to /resolve it.")
            elif d.status == Status.DELIVERED:
                out = self.propose(Action(ActionKind.RELEASE_BALANCE, Origin("monitor", f"attested_release:{d.id}"),
                                          deal_id=d.id))
                notes.append(self._monitor_note(f"Deal {d.id} with {who} was attested", out))
        p = self.plans()
        today = ws.now // 86400
        f = fc.project(ws.free, p.inflows, p.planned, p.buffer, today)
        if not f.ok:
            notes.append(f"Heads up: planned POs leave you {php(f.shortfall)} short on {_date(f.shortfall_day * 86400)}.")
        self._log("monitor_tick", notes=notes)
        return notes

    def _monitor_note(self, what: str, out: dict) -> str:
        if out["status"] == "executed":
            return f"{what}: done at Tier {out['tier']}. Tx {out['tx']}"
        if out["status"] == "needs_confirmation":
            return f"{what}: needs your confirmation.\n{out['card']}"
        return f"{what}: not done. " + " ".join(out.get("reasons", [out.get("error", "")]))

