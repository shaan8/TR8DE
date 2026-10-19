"""Negotiation endpoints: buyer workspace, supplier console, local WhatsApp simulator and the live Cloud API webhook.

Trust boundaries:
  * /api/negotiations/*  the buyer's console (same trust as the owner chat). Never returns supplier mandates.
  * /api/supplier/*      the supplier's console, authorised by a per-supplier token. Never returns buyer limits.
  * /api/sim/whatsapp/*  local simulator: messages are labelled "simulator" and never reach WhatsApp.
  * /webhooks/whatsapp   Meta's webhook: GET verification, POST only with a valid X-Hub-Signature-256.
Supplier text from any channel goes to the negotiation engine only, never to Tiwala.handle (the owner's path).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

router = APIRouter()
_svc = None
_svc_lock = threading.Lock()
_SECRET: Optional[str] = None
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "reports" / "negotiation"


def svc():
    global _svc
    with _svc_lock:
        if _svc is None:
            from tiwala_agent.llm import negotiation_llms
            from tiwala_agent.negotiation_service import NegotiationService
            from .server import live
            t = live()
            try:
                m = negotiation_llms()
            except (KeyError, ValueError):  # no model key: rule-based buyer, scripted supplier agent
                m = {"negotiator": None, "interpreter": None, "supplier": None, "supplier_model": ""}
            _svc = NegotiationService(t, Path(t.data) / "negotiation", m["negotiator"], m["interpreter"],
                                      m["supplier"], m["supplier_model"])
        return _svc


def _err(e: Exception):
    from tiwala_agent.negotiation import NegotiationError
    if isinstance(e, (NegotiationError, ValueError, KeyError)):
        raise HTTPException(400, str(e))
    raise e


def _secret() -> str:
    """Signing key for supplier tokens. Kept in the data directory (owner-only file) so tokens survive restarts;
    TIWALA_SUPPLIER_CONSOLE_SECRET overrides it. Deleting the file revokes every supplier token."""
    global _SECRET
    if _SECRET is None:
        _SECRET = os.environ.get("TIWALA_SUPPLIER_CONSOLE_SECRET", "")
        if not _SECRET:
            from .server import HERE, _load_env
            _load_env()
            f = Path(os.environ.get("TIWALA_DATA", str(HERE.parents[1] / "agent" / "data"))) / "supplier_token_secret"
            f.parent.mkdir(parents=True, exist_ok=True)
            if not f.exists():
                fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as fh:
                    fh.write(secrets.token_hex(32))
            _SECRET = f.read_text().strip()
    return _SECRET


def supplier_token(addr: str) -> str:
    return hmac.new(_secret().encode(), addr.lower().encode(), hashlib.sha256).hexdigest()[:32]


def _fixture(name: str) -> dict:
    p = FIXTURES / f"{name}.json"
    if not name.replace("_", "").isalnum() or not p.exists():
        raise HTTPException(404, f"unknown negotiation fixture {name!r}")
    return json.loads(p.read_text())


# ---------------------------------------------------------------- buyer workspace


class OpenReq(BaseModel):
    supplier: str
    product: str
    mode: str  # agent (simulated supplier agent) | whatsapp | api (the supplier's own system)
    desired_qty: int
    min_qty: int
    target_unit_price_php: float
    max_total_php: float
    min_reserve_php: float
    preferred_delivery: str  # YYYY-MM-DD
    latest_delivery: str
    opening_deposit_pct: float = 10


class TermsReq(BaseModel):
    quantity: int
    unit_price_php: float
    deposit_pct: float
    deliver_by: str  # YYYY-MM-DD (end of day, owner's time zone) or unix seconds
    note: str = ""


def _terms(r: TermsReq):
    from tiwala_agent.core import _parse_deadline
    from tiwala_agent.models import PHP
    from tiwala_agent.negotiation import Terms
    when = int(r.deliver_by) if r.deliver_by.strip().isdigit() else _parse_deadline(r.deliver_by)  # unix seconds or date
    return Terms(int(r.quantity), round(r.unit_price_php * PHP), round(r.deposit_pct * 100), when)


@router.get("/api/negotiations")
def list_negotiations(fixture: Optional[str] = Query(None)):
    if fixture:
        f = _fixture(fixture)
        return {"negotiations": [f["buyer"]], "simulated": True, "whatsapp": f.get("whatsapp", {}), "fixture": f["meta"]}
    from .server import network
    s = svc()
    return {"negotiations": [s.buyer_dict(n) for n in s.engine.store.all()[:20]], **network(s.t),
            "whatsapp": s.wa.cfg.status(), "escalations": s.escalations[-10:],
            "payees": [{"name": e.name, "address": a, "agent": s.mandates.get(a) is not None,
                        "whatsapp": (lambda c: c.channel if c and c.opted_in else None)(s.wa.contacts.get(a)),
                        "api": s.api_seen(a) is not None}
                       for a, e in s.t.directory.items()]}


@router.post("/api/negotiations")
def open_negotiation(r: OpenReq):
    from tiwala_agent.core import _parse_deadline
    from tiwala_agent.models import PHP
    from tiwala_agent.negotiation import BuyerConstraints
    s = svc()
    try:
        c = BuyerConstraints(r.desired_qty, r.min_qty, round(r.max_total_php * PHP), round(r.min_reserve_php * PHP),
                             _parse_deadline(r.latest_delivery), round(r.target_unit_price_php * PHP),
                             _parse_deadline(r.preferred_delivery), round(r.opening_deposit_pct * 100))
        n = s.open(r.supplier, r.product, c, r.mode)
    except Exception as e:
        _err(e)
    if n.mode == "agent":
        s.run_agent_background(n.id)
    return s.buyer_dict(n)


@router.get("/api/negotiations/{nid}")
def get_negotiation(nid: str):
    s = svc()
    try:
        return s.buyer_dict(s.engine.store.get(nid))
    except Exception as e:
        _err(e)


@router.post("/api/negotiations/{nid}/counter")
def counter(nid: str, r: TermsReq):
    s = svc()
    try:
        n = s.engine.owner_counter(nid, _terms(r), r.note[:200])
    except Exception as e:
        _err(e)
    if n.mode == "agent":
        s.run_agent_background(n.id)
    return s.buyer_dict(n)


@router.post("/api/negotiations/{nid}/{what}")
def close_or_escrow(nid: str, what: str, fixture: Optional[str] = Query(None)):
    if fixture:
        f = _fixture(fixture)
        return f.get("after", {}).get(what, {"status": "fixture"})
    s = svc()
    try:
        if what in ("reject", "cancel"):
            return s.buyer_dict(s.engine.owner_close(nid, cancel=what == "cancel"))
        if what == "escrow":
            out = s.request_escrow(nid)
            return {"result": {k: v for k, v in out.items() if k != "events"}, "events": out.get("events", []),
                    "negotiation": s.buyer_dict(s.engine.store.get(nid))}
        if what == "run":
            return {"started": s.run_agent_background(nid)}
    except Exception as e:
        _err(e)
    raise HTTPException(404, "unknown action")


# ---------------------------------------------------------------- supplier console


def _auth(addr: str, token: str, request: Optional[Request] = None):
    """Supplier token from `Authorization: Bearer <token>` (API clients) or ?token= (the supplier web page)."""
    h = request.headers.get("authorization", "") if request is not None else ""
    token = h[7:].strip() if h.lower().startswith("bearer ") else token
    if not addr or not token or not hmac.compare_digest(token, supplier_token(addr)):
        raise HTTPException(403, "supplier token required")
    if request is not None and h:  # an API client, not the web page: remember it is connected
        try:
            svc().mark_api_seen(addr)
        except Exception:
            pass


class MandateReq(BaseModel):
    list_unit_price_php: float
    min_unit_price_php: float
    available_qty: int
    min_order_qty: int
    earliest_delivery: str
    min_deposit_pct: float
    deposit_tiers: list = []  # [[min_qty, pct], ...]
    agent_may_accept: bool = True


class SupplierMove(BaseModel):
    type: str  # accept | counter | reject
    base_version: int
    terms: Optional[TermsReq] = None
    proposal_id: str = ""
    terms_hash: str = ""
    reason: str = ""


@router.get("/api/supplier")
def supplier_home(request: Request, supplier: str = "", token: str = "", fixture: Optional[str] = Query(None)):
    if fixture:
        return _fixture(fixture)["supplier"]
    _auth(supplier, token, request)
    s = svc()
    m = s.mandates.get(supplier)
    return {"supplier": supplier, "name": (s.t.directory.get(supplier) or type("x", (), {"name": "?"})).name,
            "mandate": m.to_dict() if m else None,
            "negotiations": [s.supplier_dict(n) for n in s.engine.store.all() if n.supplier_address.lower() ==
                             supplier.lower()][:10]}


@router.put("/api/supplier/mandate")
def put_mandate(request: Request, supplier: str, r: MandateReq, token: str = ""):
    from tiwala_agent.core import _parse_deadline
    from tiwala_agent.models import PHP
    from tiwala_agent.supplier_agent import SupplierMandate
    _auth(supplier, token, request)
    try:
        m = SupplierMandate(supplier, round(r.list_unit_price_php * PHP), round(r.min_unit_price_php * PHP),
                            r.available_qty, r.min_order_qty, _parse_deadline(r.earliest_delivery),
                            round(r.min_deposit_pct * 100), [[int(q), round(float(p) * 100)] for q, p in r.deposit_tiers],
                            r.agent_may_accept)
        svc().mandates.put(m)
    except Exception as e:
        _err(e)
    return {"ok": True, "mandate": m.to_dict()}


@router.post("/api/supplier/negotiations/{nid}/{what}")
def supplier_act(request: Request, nid: str, what: str, supplier: str, token: str = "",
                 move: Optional[SupplierMove] = None):
    _auth(supplier, token, request)
    s = svc()
    try:
        n = s.engine.store.get(nid)
        if n.supplier_address.lower() != supplier.lower():
            raise HTTPException(403, "not your negotiation")
        if what in ("takeover", "handback"):
            n = s.engine.set_controller(nid, "human" if what == "takeover" else "agent", n.supplier_identity)
            if what == "handback":
                s.run_agent_background(nid)
        elif what == "move" and move:
            if n.controller != "human":
                raise HTTPException(409, "take over from your agent first")
            act = {"type": move.type, "proposal_id": move.proposal_id, "terms_hash": move.terms_hash,
                   "reason": move.reason}
            if move.type == "counter" and move.terms:
                act.update(terms=_terms(move.terms), note=move.terms.note[:200])
            via = "supplier_api" if n.mode == "api" else "supplier_console"
            n = s.engine.supplier_action(nid, act, n.supplier_identity, via, move.base_version)
            if n.mode == "agent":
                s.run_agent_background(nid)
        else:
            raise HTTPException(404, "unknown action: use move, takeover or handback")
    except HTTPException:
        raise
    except Exception as e:
        _err(e)
    return s.supplier_dict(n)


# ---------------------------------------------------------------- local WhatsApp simulator


class SimMsg(BaseModel):
    supplier: str
    text: str


@router.post("/api/sim/whatsapp/contact")
def sim_contact(r: SimMsg):
    """Register the simulator as this supplier's WhatsApp, with a recorded demo opt-in. Local only."""
    from tiwala_agent.whatsapp import Contact
    s = svc()
    if r.supplier not in s.t.directory:
        raise HTTPException(400, "not a saved payee")
    s.wa.contacts.put(Contact(r.supplier, f"sim:{r.supplier.lower()}", "simulator", opted_in_at=int(time.time()),
                              opt_in_source="simulator demo opt-in (not a real WhatsApp consent)"))
    return {"ok": True, "supplier_link": f"/?view=supplier&supplier={r.supplier}&token={supplier_token(r.supplier)}"}


@router.post("/api/sim/whatsapp/inbound")
def sim_inbound(r: SimMsg):
    from tiwala_agent.whatsapp import Inbound
    s = svc()
    m = Inbound(f"sim-{secrets.token_hex(6)}", f"sim:{r.supplier.lower()}", int(time.time()), r.text[:1000])
    out = s.wa.handle(m, "simulator")
    nid = out.get("negotiation") or s.find_open(r.supplier)
    return {"result": out, "negotiation": s.buyer_dict(s.engine.store.get(nid)) if nid else None}


@router.get("/api/sim/supplier-link")
def sim_supplier_link(supplier: str):
    """Demo convenience on one machine: the supplier console link. In a real deployment the supplier gets this
    through their own onboarding, never from the buyer's console."""
    if os.environ.get("TIWALA_DEMO_LINKS", "1") != "1":
        raise HTTPException(404, "disabled")
    return {"link": f"/?view=supplier&supplier={supplier}&token={supplier_token(supplier)}"}


# ---------------------------------------------------------------- live WhatsApp Cloud API webhook


def _wa_cfg():
    """WhatsApp settings without building the live agent: the public webhook checks Meta's token or signature first."""
    from tiwala_agent.whatsapp import Config
    from .server import _load_env
    _load_env()
    return Config.from_env()


@router.get("/webhooks/whatsapp")
def wa_verify(request: Request):
    from tiwala_agent.whatsapp import verify_subscription
    q = request.query_params
    ch = verify_subscription(_wa_cfg(), q.get("hub.mode", ""), q.get("hub.verify_token", ""),
                             q.get("hub.challenge", ""))
    if ch is None:
        raise HTTPException(403, "verification failed")
    return PlainTextResponse(ch)


@router.post("/webhooks/whatsapp")
async def wa_event(request: Request):
    from tiwala_agent.whatsapp import parse_webhook, valid_signature
    raw = await request.body()
    if not valid_signature(_wa_cfg(), raw, request.headers.get("x-hub-signature-256", "")):
        print(f"whatsapp: bad signature, {len(raw)} bytes", flush=True)  # nothing built or stored for unsigned posts
        raise HTTPException(403, "bad signature")
    s = svc()
    try:
        msgs, sts = parse_webhook(json.loads(raw))
    except ValueError:
        return {"ok": True}  # acknowledged so Meta does not retry garbage forever
    for m in msgs:
        if m.phone_number_id and s.wa.cfg.phone_number_id and m.phone_number_id != s.wa.cfg.phone_number_id:
            continue
        s.wa.handle(m, "live")
    for st in sts:
        s.wa.status(st)
    return {"ok": True}
