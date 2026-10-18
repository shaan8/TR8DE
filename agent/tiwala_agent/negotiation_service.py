"""Glue between the negotiation engine, Tiwala's payment pipeline, WhatsApp and supplier agents.

Escrow handoff (request_escrow) is idempotent: it returns the existing deal if the negotiation already has one or if
a deal with the same on-chain reference exists, returns the same pending card on a repeated request, and rechecks
funds, reserve, supplier status, deposit ceiling and expiry before drafting. The deal is created only when the owner
confirms the card in their own words, through Tiwala's policy, Checker, Gate and signer.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from . import forecast as fc
from .core import Tiwala, _date, _when
from .llm import LLM
from .models import PHP, Action, php
from .negotiation import (BuyerConstraints, BuyerView, Engine, Negotiation, NegotiationError, State, Store, TERMINAL,
                          Terms, buyer_checks, cash_impact, escrow_ref, passes)
from .reputation import DpPolicy, dp_cap, score
from .supplier_agent import MandateStore, SupplierAgent, SupplierMandate, run_agent_turns
from .whatsapp import Config, Contact, Gateway, redact


class NegotiationService:
    def __init__(self, tiwala: Tiwala, root: str | Path, negotiator: Optional[LLM] = None,
                 interpreter: Optional[LLM] = None, supplier_llm: Optional[LLM] = None, supplier_model: str = "",
                 wa_cfg: Optional[Config] = None, wa_sender=None):
        self.t = tiwala
        root = Path(root)
        self.mandates = MandateStore(root / "supplier")  # supplier side
        self.supplier_llm, self.supplier_model = supplier_llm, supplier_model
        self.escalations: list[dict] = []
        self.engine = Engine(Store(root / "negotiations"), self.buyer_view, self._log, negotiator, interpreter,
                             send=self._send)
        self.wa = Gateway(root / "whatsapp", wa_cfg or Config.from_env(), self.engine.supplier_text, self.find_open,
                          self._escalate, self._log, sender=wa_sender)
        self.t.on_executed.append(self._on_executed)
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
                raise NegotiationError("This supplier has no opted-in WhatsApp contact on file.")
            identity, channel, kind = contact.wa_id, contact.channel, "none"
        elif mode == "agent":
            m = self.mandates.get(addr)
            if m is None:
                raise NegotiationError("This supplier has not set up an agent mandate.")
            identity = contact.wa_id if contact and contact.opted_in else f"supplier-console:{addr.lower()}"
            channel, kind = "local", self.agent_for(addr).kind
        else:
            raise NegotiationError("mode must be whatsapp or agent")
        return self.engine.open(self.t.wallet, self.t.directory[addr].name, addr, product, c, mode, channel, identity,
                                kind, proposal_ttl_s=3600 if mode == "agent" else 86400)

    def agent_for(self, addr: str) -> SupplierAgent:
        m = self.mandates.get(addr)
        if m is None:
            raise NegotiationError("no supplier mandate")
        return SupplierAgent(m, self.mandates, self.supplier_llm, self.supplier_model)

    def run_agent(self, nid: str) -> Negotiation:
        n = self.engine.store.get(nid)
        if n.mode != "agent":
            raise NegotiationError("this negotiation has no supplier agent")
        return run_agent_turns(self.engine, nid, self.agent_for(n.supplier_address))

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

    # ---------------------------------------------------------- escrow handoff

    def request_escrow(self, nid: str) -> dict:
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
                       "simulator_text": "WhatsApp simulator", "live_text": "WhatsApp"}.get(sup_acc.get("via", ""),
                                                                                       sup_acc.get("via", "?"))
            via = f"{channel}, {redact(sup_acc.get('identity', ''))}"
            summary = (f"The owner asked to put negotiated agreement NEG-{n.id} v{p.version} into escrow. Agreed with "
                       f"{n.supplier_name}: {tt.quantity} units of {n.product} at {php(tt.unit_price)} each = "
                       f"{php(tt.total)} total, deposit {tt.deposit_bps / 100:g}% ({php(tt.deposit)}) released after "
                       f"creation, delivery by {_when(tt.deliver_by)}, PO reference {ref}. Supplier acceptance: {via}. "
                       f"Terms hash {p.terms_hash[:16]}.")
            out = t.propose_negotiated(detail, n.supplier_address, tt.total, tt.deposit_bps, tt.deliver_by, ref,
                                       summary, f"NEG-{n.id} v{p.version}", via)
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
