"""Glue between the negotiation engine, TR8DE's payment pipeline, WhatsApp and supplier agents.

Escrow handoff (request_escrow) is idempotent: it returns the existing deal if the negotiation already has one or if
a deal with the same on-chain reference exists, returns the same pending card on a repeated request, and rechecks
funds, reserve, supplier status, deposit ceiling and expiry before drafting. The deal is created only when the owner
confirms the card in their own words, through TR8DE's policy, Checker, Gate and signer.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from . import forecast as fc
from .core import Tiwala, _date, _when
from .llm import LLM
from .models import PHP, Action, ActionKind, php
from .negotiation import (BuyerConstraints, BuyerView, Engine, Negotiation, NegotiationError, Proposal, State, Store,
                          TERMINAL, Terms, buyer_checks, cash_impact, escrow_ref, passes)
from .privacy import RedactingLLM
from .reputation import DpPolicy, dp_cap, score
from .supplier_agent import MandateStore, SupplierAgent, SupplierMandate, run_agent_turns
from .telegram import Poller, TelegramSender, TgConfig
from .whatsapp import Config, Contact, Gateway, redact


class NegotiationService:
    def __init__(self, tiwala: Tiwala, root: str | Path, negotiator: Optional[LLM] = None,
                 interpreter: Optional[LLM] = None, supplier_llm: Optional[LLM] = None, supplier_model: str = "",
                 wa_cfg: Optional[Config] = None, wa_sender=None, tg_cfg: Optional[TgConfig] = None, tg_call=None):
        self.t = tiwala
        root = Path(root)
        self.mandates = MandateStore(root / "supplier")  # supplier side
        self.supplier_llm, self.supplier_model = supplier_llm, supplier_model
        self.escalations: list[dict] = []
        wrap = lambda m: RedactingLLM(m) if m is not None else None  # supplier text can carry phones, accounts
        self.engine = Engine(Store(root / "negotiations"), self.buyer_view, self._log, wrap(negotiator),
                             wrap(interpreter), send=self._send)
        self.tg_cfg = tg_cfg or TgConfig.from_env()
        tg_kw = {"call": tg_call} if tg_call else {}
        self.wa = Gateway(root / "whatsapp", wa_cfg or Config.from_env(), self._supplier_text, self.find_open,
                          self._escalate, self._log, sender=wa_sender, tg=TelegramSender(self.tg_cfg, **tg_kw))
        self.tg = Poller(self.wa, self.tg_cfg, root / "whatsapp",
                         lambda a: self.t.directory[a].name if a in self.t.directory else a, **tg_kw)
        self.t.on_executed.append(self._on_executed)
        self.t.before_confirm.append(self._recheck_before_confirm)
        self.t.negotiations = self
        self._runs: dict[str, threading.Thread] = {}
        self._views: dict[str, tuple[float, BuyerView]] = {}  # supplier -> (read at, view); escrow always reads fresh

    # ---------------------------------------------------------- plumbing

    def _log(self, event: str, **data) -> None:
        self.t.audit.write(event, **data)

    def _escalate(self, nid: str, note: str) -> None:
        self.escalations.append({"negotiation": nid, "note": note, "ts": self.engine.now()})
        try:
            with self.engine.store.lock:
                n = self.engine.store.get(nid)
                n.escalated = True
                n.note("escalated", note, self.engine.now())
                self.engine.store.save(n)
        except NegotiationError:
            pass
        self._log("negotiation_escalated", negotiation=nid, note=note)

    def _send(self, n: Negotiation, text: str, proposal) -> None:
        if self.wa.contacts.get(n.supplier_address):  # WhatsApp mode, or agent mode with notifications on
            self.wa.send(n.id, n.supplier_address, text, proposal.id if proposal else None)

    def find_open(self, supplier_address: str) -> Optional[str]:
        for n in self.engine.store.all():
            if n.supplier_address.lower() == supplier_address.lower() and State(n.state) not in TERMINAL:
                return n.id
        return None

    # ---------------------------------------------------------- buyer view, fresh from chain

    def buyer_view(self, n: Negotiation, fresh: bool = False, ttl: float = 15.0) -> BuyerView:
        hit = self._views.get(n.supplier_address)
        if not fresh and hit and time.time() - hit[0] < ttl:
            return hit[1]
        v = self._read_view(n)
        self._views[n.supplier_address] = (time.time(), v)
        return v

    def _read_view(self, n: Negotiation) -> BuyerView:
        t = self.t
        ws = t.chain.wallet_state(t.wallet)
        sup = n.supplier_address
        entry = t.directory.get(sup)
        listed, active_at = t.chain.supplier_onchain(t.wallet, sup)
        ok = bool(entry) and listed and active_at <= ws.now
        why = ("Saved payee, active on the wallet contract." if ok else
               "Not a saved payee." if not entry else "Removed from the wallet whitelist." if not listed else
               f"In its waiting period until {_when(active_at)}.")
        closed = t.chain.closed_deals()
        rep = score(closed, sup)
        cap = dp_cap(rep, t.wallet, closed, DpPolicy(t.dp.dp_min_bps, t.dp.dp_max_bps, t.dp.stranger_cap_bps,
                                                     ws.max_down_bps))
        ceiling = min(cap.cap_bps, ws.max_down_bps)
        plans, today = t.plans(), ws.now // 86400

        def shortfall(terms: Terms):
            f = fc.with_new_deal(ws.free, plans.inflows, plans.planned, plans.buffer, today, terms.total, today)
            return None if f.ok else (f.shortfall_day, f.shortfall)

        return BuyerView(ws.now, ws.free, ws.per_deal_cap, ws.daily_remaining, ceiling,
                         f"reputation cap {cap.cap_bps / 100:g}%, contract ceiling {ws.max_down_bps / 100:g}%",
                         ok, why, shortfall)

    # ---------------------------------------------------------- opening and agents

    def open(self, supplier_name: str, product: str, c: BuyerConstraints, mode: str) -> Negotiation:
        addr = next((a for a, e in self.t.directory.items() if e.name.lower() == supplier_name.strip().lower()), None)
        if addr is None:
            raise NegotiationError(f"{supplier_name} is not a saved payee. Save the supplier first.")
        contact = self.wa.contacts.get(addr)
        if mode == "whatsapp":
            if contact is None or not contact.opted_in:
                raise NegotiationError("This supplier has no opted-in WhatsApp or Telegram contact on file.")
            identity, channel, kind = contact.wa_id, contact.channel, "none"
        elif mode == "agent":
            m = self.mandates.get(addr)
            if m is None:
                raise NegotiationError("This supplier has not set up an agent mandate.")
            identity = contact.wa_id if contact and contact.opted_in else f"supplier-console:{addr.lower()}"
            channel, kind = "local", self.agent_for(addr).kind
        elif mode == "api":  # the supplier's own system answers through the supplier API with its token
            identity, channel, kind = f"supplier-api:{addr.lower()}", "api", "external"
        else:
            raise NegotiationError("mode must be whatsapp, agent or api")
        return self.engine.open(self.t.wallet, self.t.directory[addr].name, addr, product, c, mode, channel, identity,
                                kind, proposal_ttl_s=3600 if mode == "agent" else 86400)

    # ---------------------------------------------------------- linking a supplier's chat (owner only)

    def payee(self, name_or_addr: str) -> str:
        q = name_or_addr.strip().lower()
        hits = [a for a, e in self.t.directory.items() if q in (a.lower(), e.name.lower())]
        if not hits:
            hits = [a for a, e in self.t.directory.items() if q and e.name.lower().startswith(q)]
        if len(hits) != 1:
            names = ", ".join(e.name for e in self.t.directory.values())
            raise NegotiationError(f"No single saved payee matches {name_or_addr.strip()!r}. Saved payees: {names}.")
        return hits[0]

    def invite_telegram(self, name_or_addr: str) -> str:
        if not self.tg_cfg.token:
            raise NegotiationError("Telegram is off: add TELEGRAM_BOT_TOKEN (from @BotFather) and TELEGRAM_LIVE_SEND=1 "
                                   "to .env and restart.")
        addr = self.payee(name_or_addr)
        link = self.tg.invite_link(addr)
        self._log("telegram_invite_created", supplier=addr)
        note = "" if self.tg_cfg.live_send else " Note: TELEGRAM_LIVE_SEND is not 1, so the bot cannot reply yet."
        code = link.rsplit("start=", 1)[1]
        return (f"Send this link to {self.t.directory[addr].name}: {link}\nIt works once, for 7 days. When they press "
                f"Start their chat is linked and you can negotiate with them. If they had chatted with the bot before, "
                f"Telegram may open the chat without the code: they then send /start {code} there.{note}")

    def link_whatsapp(self, name_or_addr: str, number: str) -> str:
        import re as _re
        addr = self.payee(name_or_addr)
        wa = _re.sub(r"\D", "", number)
        if not 8 <= len(wa) <= 15:
            raise NegotiationError("That does not look like a WhatsApp number: use the country code, e.g. +63 917 123 4567.")
        cfg = self.wa.cfg
        if cfg.allowed and wa not in cfg.allowed:
            raise NegotiationError("This number is not in WHATSAPP_ALLOWED_RECIPIENTS; add it there or empty that list.")
        self.wa.contacts.put(Contact(addr, wa, "live", opted_in_at=int(time.time()),
                                     opt_in_source="owner linked the number in the console and confirmed consent"))
        self._log("whatsapp_contact_linked", supplier=addr, to=redact(wa))
        gaps = [g for g in cfg.missing() if "ALLOWED_RECIPIENTS" not in g]
        return (f"Linked {self.t.directory[addr].name} to WhatsApp {redact(wa)}." +
                (" Before it can send or receive: " + " ".join(gaps) if gaps else " Ready to negotiate."))

    def mark_api_seen(self, addr: str) -> None:
        p = self.mandates.root / f"{addr.lower()}.api.json"
        p.write_text(json.dumps({"last_seen": int(time.time())}))

    def api_seen(self, addr: str, within_s: int = 7 * 86400) -> Optional[int]:
        """When the supplier's own system last called the supplier API, if recently."""
        p = self.mandates.root / f"{addr.lower()}.api.json"
        try:
            t = int(json.loads(p.read_text())["last_seen"])
        except (OSError, ValueError, KeyError):
            return None
        return t if time.time() - t < within_s else None

    def _chat_mode(self, addr: str) -> Optional[str]:
        c = self.wa.contacts.get(addr)
        if c and c.opted_in:
            return "whatsapp"
        if self.api_seen(addr):
            return "api"
        return "agent" if self.mandates.get(addr) else None

    def chat_channel(self, addr: str) -> Optional[str]:
        """How a chat-started negotiation would reach this supplier, or None."""
        mode = self._chat_mode(addr)
        if mode == "whatsapp":
            c = self.wa.contacts.get(addr)
            names = {"simulator": "WhatsApp simulator", "telegram": f"Telegram {redact(c.wa_id)}"}
            return names.get(c.channel, f"WhatsApp {redact(c.wa_id)}")
        return {"api": "the supplier's own system (API)", "agent": "supplier agent (simulated)"}.get(mode)

    def start_from_chat(self, spec: dict) -> dict:
        from .core import _parse_deadline
        addr = next(a for a, e in self.t.directory.items() if e.name == spec["supplier"])
        mode = self._chat_mode(addr) or "agent"
        bc = BuyerConstraints(spec["desired_qty"], spec["min_qty"], round(spec["max_total_php"] * PHP),
                              round(spec["min_reserve_php"] * PHP), _parse_deadline(spec["latest_delivery"]),
                              round(spec["target_unit_price_php"] * PHP), _parse_deadline(spec["preferred_delivery"]),
                              round(spec["opening_deposit_pct"] * 100))
        n = self.open(spec["supplier"], spec["product"], bc, mode)
        out = self.buyer_dict(n)
        out["channel_label"] = self.chat_channel(addr)
        if mode == "agent":
            self.run_agent_background(n.id)
            out["sent"] = "The supplier agent is answering now."
        elif mode == "api":
            out["sent"] = "The opening offer is waiting for the supplier's system to pick it up."
        else:
            last = (self.wa.outbox.for_negotiation(n.id) or [{}])[-1]
            app = "Telegram" if last.get("channel") == "telegram" else "WhatsApp"
            out["sent"] = {"sent": f"Opening offer sent on {app}." if last.get("kind") == "text" else
                           f"WhatsApp template {self.wa.cfg.template_name} sent; the offer follows when they reply.",
                           "delivered": "Opening offer shown in the WhatsApp simulator."}.get(
                last.get("status"), f"{app} message not sent: {last.get('error', 'unknown')}.")
        return out

    def agent_for(self, addr: str) -> SupplierAgent:
        m = self.mandates.get(addr)
        if m is None:
            raise NegotiationError("no supplier mandate")
        return SupplierAgent(m, self.mandates, self.supplier_llm, self.supplier_model)

    def run_agent(self, nid: str) -> Negotiation:
        n = self.engine.store.get(nid)
        if n.mode != "agent":
            raise NegotiationError("this negotiation has no supplier agent")
        n = run_agent_turns(self.engine, nid, self.agent_for(n.supplier_address))
        self.settle_if_agreed(nid)
        return n

    def run_agent_background(self, nid: str) -> bool:
        th = self._runs.get(nid)
        if th and th.is_alive():
            return False
        th = threading.Thread(target=self._safe_run, args=(nid,), daemon=True)
        self._runs[nid] = th
        th.start()
        return True

    def _safe_run(self, nid: str) -> None:
        try:
            self.run_agent(nid)
        except Exception as e:  # never retry silently
            self._log("negotiation_agent_error", negotiation=nid, error=f"{type(e).__name__}: {str(e)[:200]}")

    def running(self, nid: str) -> bool:
        th = self._runs.get(nid)
        return bool(th and th.is_alive())

    def await_settlement(self, nid: str, timeout: float = 30.0) -> None:
        """Block until the automatic escrow attempt for this negotiation has finished, for callers that need the
        settled state at once rather than on the next refresh."""
        if th := self._runs.get(f"settle-{nid}"):
            th.join(timeout)

    # ---------------------------------------------------------- escrow handoff

    def _supplier_text(self, nid: str, text: str, identity: str, msg_id: str, channel: str) -> Negotiation:
        """The gateway's hook into the engine. Settlement is attempted only after the engine's own turn has
        finished and saved, never from inside it, so nothing races the turn that produced the agreement."""
        n = self.engine.supplier_text(nid, text, identity, msg_id, channel)
        self.settle_if_agreed(n.id)
        return n

    def settle_if_agreed(self, nid: str) -> None:
        """Both sides accepted and the deal is inside the authority the owner set on the wallet contract: the agent
        settles it itself, off the caller's thread. Anything beyond that authority waits for the owner to send it to
        escrow, exactly as before, so a confirmation card is never raised behind their back."""
        try:
            n = self.engine.store.get(nid)
            if State(n.state) != State.AWAITING_BUYER_APPROVAL or not n.agreement:
                return
            p = n.by_id(n.agreement["proposal_id"])
            if p is None or not self.t.agent_may_create(n.supplier_address, p.terms.total):
                self._log("negotiation_settle_deferred", negotiation=nid, reason="beyond the agent's authority")
                return
        except Exception as e:
            self._log("negotiation_settle_deferred", negotiation=nid, error=str(e)[:200])
            return

        def go():
            try:
                self._log("negotiation_settling", negotiation=nid)
                if self.request_escrow(nid).get("status") == "needs_confirmation":
                    self._hand_escrow_back(nid)
            except Exception as e:  # a closed or expired negotiation must not take the caller down
                self._log("negotiation_settle_failed", negotiation=nid, error=str(e)[:200])
        th = threading.Thread(target=go, name=f"settle-{nid}", daemon=True)
        self._runs[f"settle-{nid}"] = th
        th.start()

    def _hand_escrow_back(self, nid: str) -> None:
        """The full review wanted the owner after the pre-check had let the agent through: the Checker said no, or a
        flag was raised. Undo the automatic attempt, so the owner sends it to escrow themselves exactly as they would
        have, rather than finding a confirmation card they never asked for."""
        if (pend := self.t.pending) and pend.action.origin.detail.split(":", 1)[0] == nid:
            self.t.pending = None
        with self.engine.store.lock:
            n = self.engine.store.get(nid)
            if State(n.state) != State.READY_FOR_ESCROW:
                return
            n.state = State.AWAITING_BUYER_APPROVAL.value
            n.handoff = {}
            n.reason = "Both sides accepted. Send it to escrow when you are ready."
            n.note("escrow_deferred", "the review asked for your confirmation; waiting for you", self.engine.now())
            self.engine.store.save(n)
        self._log("negotiation_settle_deferred", negotiation=nid, reason="the review asked for your confirmation")

    def request_escrow(self, nid: str) -> dict:
        with self.t.turn_lock:  # same order everywhere: owner turn first, then the negotiation store
            return self._request_escrow(nid)

    def _request_escrow(self, nid: str) -> dict:
        eng, t = self.engine, self.t
        with eng.store.lock:
            n = eng.store.get(nid)
            if n.handoff.get("deal_id"):
                return {"status": "already_created", "deal_id": n.handoff["deal_id"], "tx": n.handoff.get("tx")}
            if State(n.state) not in (State.AWAITING_BUYER_APPROVAL, State.READY_FOR_ESCROW):
                raise NegotiationError(f"the negotiation is {n.state.replace('_', ' ')}, not agreed")
            n, p = eng.agreed(nid)
            ref = escrow_ref(n, p)
            existing = next((d for d in t.chain.deals(t.wallet) if d.ref == ref), None)
            if existing:  # created before but not linked (crash between tx and bookkeeping)
                self._link(n, existing.id, None, None, "found on chain by reference")
                return {"status": "already_created", "deal_id": existing.id}
            if eng.now() > p.expires:
                eng._close(n, State.EXPIRED, "the agreement expired before escrow; negotiate again", tell_supplier=True)
                eng.store.save(n)
                return {"status": "expired"}
            v = self.buyer_view(n, fresh=True)  # recheck on chain state read now, never a cached view
            checks = buyer_checks(p.terms, n.constraints, v)
            if not passes(checks):
                reasons = [c.detail for c in checks if not c.ok and c.severity == "refuse"]
                n.reason = "Recheck failed: " + " ".join(reasons)
                n.note("recheck_failed", n.reason, eng.now())
                eng.store.save(n)
                self._log("negotiation_recheck_failed", negotiation=n.id, reasons=reasons)
                return {"status": "refused", "reasons": reasons}
            detail = f"{n.id}:{p.id}:{p.terms_hash}"
            if t.pending and t.pending.action.origin.detail == detail:
                return {"status": "needs_confirmation", "card": t.pending.card}
            tt = p.terms
            sup_acc = p.accepted_by.get("supplier", {})
            channel = {"supplier_agent_live_model": "supplier agent, live model",
                       "supplier_agent_scripted": "supplier agent, scripted", "supplier_console": "supplier console",
                       "simulator_text": "WhatsApp simulator", "live_text": "WhatsApp",
                       "telegram_text": "Telegram"}.get(sup_acc.get("via", ""),
                                                                                       sup_acc.get("via", "?"))
            via = f"{channel}, {redact(sup_acc.get('identity', ''))}"
            summary = (f"The owner asked to put negotiated agreement NEG-{n.id} v{p.version} into escrow. Agreed with "
                       f"{n.supplier_name}: {tt.quantity} units of {n.product} at {php(tt.unit_price)} each = "
                       f"{php(tt.total)} total, deposit {tt.deposit_bps / 100:g}% ({php(tt.deposit)}) released after "
                       f"creation, delivery by {_when(tt.deliver_by)}, PO reference {ref}. Supplier acceptance: {via}. "
                       f"Terms hash {p.terms_hash[:16]}.")
            out = t.propose_negotiated(detail, n.supplier_address, tt.total, tt.deposit_bps, tt.deliver_by, ref,
                                       summary, f"NEG-{n.id} v{p.version}", via)
            if out["status"] == "executed":  # within the agent's on-chain authority: _on_executed linked it
                self._log("negotiation_handoff", negotiation=n.id, proposal=p.id, status=out["status"], ref=ref)
                return {**out, "events": t._events}
            if out["status"] == "needs_confirmation":
                n.state = State.READY_FOR_ESCROW.value
                n.handoff = {"state": "pending", "ref": ref, "proposal": p.id}
                n.reason = "Escrow card ready: your own yes creates the deal and pays the deposit."
                n.note("escrow_requested", "confirmation card shown; waiting for your yes", eng.now())
            else:
                n.handoff = {"state": "refused", "ref": ref, "reasons": out.get("reasons", []),
                             "error": out.get("error")}
                n.reason = "Escrow refused: " + " ".join(out.get("reasons", []) or [str(out.get("error"))])
                n.note("escrow_refused", n.reason, eng.now())
            eng.store.save(n)
            self._log("negotiation_handoff", negotiation=n.id, proposal=p.id, status=out["status"], ref=ref)
            return {**out, "events": t._events}

    def _recheck_before_confirm(self, action: Action) -> list[str]:
        """The owner's yes may come minutes after the card. Re-run expiry and the buyer's hard constraints on chain
        state read now, so a card cannot outlive the agreement it was raised for."""
        if action.origin.kind != "negotiation" or action.kind != ActionKind.CREATE_DEAL:
            return []
        nid, pid, terms_hash = (action.origin.detail.split(":") + ["", ""])[:3]
        eng = self.engine
        with eng.store.lock:
            try:
                n = eng.store.get(nid)
            except NegotiationError:
                return ["the negotiation behind this card no longer exists"]
            p = n.by_id(n.agreement["proposal_id"]) if n.agreement else None
            if p is None or p.id != pid or p.terms_hash != terms_hash:
                return ["the agreed terms changed after this card was raised"]
            if State(n.state) not in (State.AWAITING_BUYER_APPROVAL, State.READY_FOR_ESCROW):
                return [f"the negotiation is {n.state.replace('_', ' ')}, not agreed"]
            if eng.now() > p.expires:
                eng._close(n, State.EXPIRED, "the agreement expired before escrow; negotiate again", tell_supplier=True)
                eng.store.save(n)
                return ["the agreement expired before your yes; negotiate again"]
            checks = buyer_checks(p.terms, n.constraints, self.buyer_view(n, fresh=True))
            reasons = [c.detail for c in checks if not c.ok and c.severity == "refuse"]
            if reasons:
                n.state, n.handoff = State.AWAITING_BUYER_APPROVAL.value, {}
                n.reason = "Recheck failed: " + " ".join(reasons)
                n.note("recheck_failed", n.reason, eng.now())
                eng.store.save(n)
                self._log("negotiation_recheck_failed", negotiation=n.id, reasons=reasons)
            return reasons

    def _on_executed(self, action: Action, out: dict) -> None:
        if action.origin.kind != "negotiation":
            return
        nid = action.origin.detail.split(":", 1)[0]
        with self.engine.store.lock:
            try:
                n = self.engine.store.get(nid)
            except NegotiationError:
                return
            dp = out.get("down_payment") or {}
            self._link(n, out.get("deal_id"), out.get("tx"), dp.get("tx"),
                       "deposit released" if dp.get("status") == "executed" else
                       f"deposit not released: {'; '.join(dp.get('reasons', [dp.get('error', '')]) or [''])}")

    def _link(self, n: Negotiation, deal_id, tx, down_tx, note: str) -> None:
        n.handoff.update({"state": "created", "deal_id": deal_id, "tx": tx, "down_tx": down_tx, "note": note})
        n.state = State.ESCROW_CREATED.value
        n.reason = f"Escrow created: deal {deal_id}."
        self._views.clear()
        n.note("escrow_created", f"deal {deal_id}; {note}", self.engine.now())
        self.engine.store.save(n)
        self._log("negotiation_escrow_linked", negotiation=n.id, deal_id=deal_id, tx=tx, down_tx=down_tx)
        p = n.by_id(n.agreement["proposal_id"]) if n.agreement else None
        self._send(n, f"Escrow created for offer v{p.version if p else '?'}: deal {deal_id}. The full amount is "
                      f"locked; {note}. The balance is released after the buyer confirms delivery.", p)

    # ---------------------------------------------------------- views

    def buyer_dict(self, n: Negotiation) -> dict:
        """The buyer console's view: constraint checks and cash impact for the current offer. No supplier mandate."""
        cur = n.current()
        props = n.props()
        out = n.to_dict()
        if State(n.state) in TERMINAL:  # closed: show the record, no live chain reads
            out.update(view=None, checks=None, cash=None, diff={}, outbox=self.wa.outbox.for_negotiation(n.id),
                       running=False, pending_card=None, supplier_identity=redact(n.supplier_identity))
            return out
        v = self.buyer_view(n)
        out["constraints"] = {**out["constraints"], "latest_delivery_text": _date(n.constraints.latest_delivery)}
        out["supplier_identity"] = redact(n.supplier_identity) if not n.supplier_identity.startswith(
            ("sim:", "supplier-console:", "agent:")) else n.supplier_identity
        out["view"] = {"free": v.free, "deposit_ceiling_bps": v.deposit_ceiling_bps,
                       "deposit_ceiling_reason": v.deposit_ceiling_reason, "supplier_ok": v.supplier_ok,
                       "supplier_reason": v.supplier_reason, "now": v.now}
        if cur:
            out["checks"] = [c.to_dict() for c in buyer_checks(cur.terms, n.constraints, v)]
            out["cash"] = cash_impact(cur.terms, n.constraints, v)
            prev = props[-2] if len(props) > 1 else None
            out["diff"] = ({k: [prev.terms.to_dict()[k], cur.terms.to_dict()[k]] for k in cur.terms.to_dict()
                            if prev.terms.to_dict()[k] != cur.terms.to_dict()[k]} if prev else {})
        out["outbox"] = self.wa.outbox.for_negotiation(n.id)
        out["running"] = self.running(n.id)
        out["pending_card"] = self.t.pending.card if self.t.pending and self.t.pending.action.origin.detail.startswith(
            f"{n.id}:") else None
        return out

    def supplier_dict(self, n: Negotiation) -> dict:
        """The supplier console's view: public negotiation plus the supplier's own mandate. No buyer limits."""
        m = self.mandates.get(n.supplier_address)
        pub = n.public()
        pub["mandate"] = m.to_dict() if m else None
        pub["agent_kind"] = n.agent_kind
        pub["running"] = self.running(n.id)
        return pub
