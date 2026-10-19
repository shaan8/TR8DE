"""FastAPI over the Tiwala core for the React console (ui/).

    cd agent && ../.venv/bin/uvicorn console.server:app --port 8000

Every endpoint takes ?fixture=<name>: it then replays audit.jsonl slices and reports/live transcripts
(see fixtures.py) with no LLM or chain call. Without it the endpoint drives the live agent, built the
same way as the Streamlit app.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth as authmod
from . import fixtures as fx

HERE = Path(__file__).resolve().parent
DIST = HERE.parents[1] / "ui" / "dist"
PUBLIC_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
STAGE = {"LOCKED": "Locked", "DOWN_PAID": "DP paid", "DELIVERED": "Delivered", "COMPLETED": "Completed",
         "REFUNDED": "Refunded", "DISPUTED": "Disputed"}

app = FastAPI(title="Tiwala console", docs_url=None, redoc_url=None, openapi_url=None)


class Msg(BaseModel):
    text: str


class Confirm(BaseModel):
    code: Optional[str] = None  # last 4 characters of a payee address


# ---------------------------------------------------------------- owner login


class Login(BaseModel):
    username: str
    password: str


def _auth() -> authmod.Auth:
    global AUTH
    if AUTH is None:
        _load_env()
        AUTH = authmod.Auth.from_env()
    return AUTH


AUTH: Optional[authmod.Auth] = None


@app.post("/api/login")
def login(r: Login, request: Request, response: Response):
    a = _auth()
    if not a.configured:
        raise HTTPException(503, "No login is set up. Run: cd agent && ../.venv/bin/python -m console.auth set-password <name>")
    if request.headers.get("x-tiwala") != "1" or not authmod.same_origin(request):
        raise HTTPException(403, "Cross-site request refused.")
    client = authmod.client_of(request)
    wait = a.locked_for(client)
    if wait:
        raise HTTPException(429, f"Too many failed sign-ins. Try again in {int(wait // 60) + 1} min.")
    sid = a.login(client, r.username[:64], r.password[:256])
    if sid is None:
        _live_log("login_failed", client=client)
        raise HTTPException(401, "Wrong username or password.")
    _live_log("login_ok", client=client)
    response.set_cookie(authmod.COOKIE, sid, max_age=authmod.SESSION_TTL_S, httponly=True, samesite="strict",
                        secure=authmod.is_https(request), path="/")
    return {"ok": True, "user": a.user}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    _auth().logout(request.cookies.get(authmod.COOKIE))
    response.delete_cookie(authmod.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/session")
def session(request: Request):
    a = _auth()
    signed = authmod.test_bypass(request) or a.valid(request.cookies.get(authmod.COOKIE))
    return {"signed_in": signed, "configured": a.configured}


def _live_log(event: str, **data) -> None:
    print(f"auth: {event} {data}", flush=True)  # server log only; the audit chain has a single writer


# ---------------------------------------------------------------- live agent

_live = None
_live_lock = threading.Lock()
_alerts: list[dict] = []


def _load_env() -> None:
    env = HERE.parents[1] / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = "" if line.lstrip().startswith("#") else line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":  # quoted, so a shell can source .env safely
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)
    os.environ.setdefault("RPC_URL", os.environ.get("AGENT_RPC_URL") or PUBLIC_RPC)
    if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ.setdefault("TIWALA_LLM_PROVIDER", "openrouter")


def live():
    global _live
    with _live_lock:
        if _live is None:
            from tiwala_agent.audit import AuditLog
            from tiwala_agent.chain import Chain, OwnerConsole
            from tiwala_agent.core import Tiwala
            from tiwala_agent.llm import from_env
            _load_env()
            root = HERE.parents[1]
            dep = json.loads(Path(os.environ.get("TIWALA_DEPLOYMENT", root / "deployments" / "11155111.json")).read_text())
            chain = Chain(os.environ["RPC_URL"], dep, os.environ["AGENT_PRIVATE_KEY"])
            owner = OwnerConsole(chain, dep["demoWallet"], os.environ["OWNER_PRIVATE_KEY"]) \
                if os.environ.get("OWNER_PRIVATE_KEY") else None
            audit = AuditLog(os.environ.get("TIWALA_AUDIT", str(root / "agent" / "logs" / "audit.jsonl")))
            data = os.environ.get("TIWALA_DATA", str(root / "agent" / "data"))
            from tiwala_agent.core import llms_or_offline
            _live = Tiwala(chain, dep["demoWallet"], data, llms_or_offline(from_env), audit, owner)
        return _live


NETWORKS = {11155111: ("Sepolia testnet", "https://sepolia.etherscan.io"), 31337: ("Local test chain", None)}


def network(t) -> dict:
    cid = t.chain.w3.eth.chain_id
    name, explorer = NETWORKS.get(cid, (f"Chain {cid}", None))
    return {"network": name, "explorer": explorer}


def _live_state() -> dict:
    from tiwala_agent.guard import tag_contract
    from tiwala_agent.models import PHP
    t = live()
    ws = t.chain.wallet_state(t.wallet)
    names = t.names()
    deals = []
    for d in t.chain.deals(t.wallet):
        tag = tag_contract(d.ref)
        deals.append({"id": d.id, "supplier": names.get(d.supplier, d.supplier), "ref": tag.text,
                      "ref_flags": list(tag.flags), "total_php": d.total / PHP, "down_pct": d.down_bps / 100,
                      "deadline": d.deadline, "stage": STAGE[d.status.name]})
    pending = {"card": fx.parse_card(t.pending.card)} if t.pending else None
    payees = []
    for addr, e in t.directory.items():
        listed, active_at = t.chain.supplier_onchain(t.wallet, addr)
        payees.append({"name": e.name, "address": addr, "listed": listed, "active_at": active_at,
                       "changed_at": e.address_changed_at})
    pp = t.pending_payee
    return {
        "fixture": None, "title": "Live", "synthetic": False,
        "wallet": {"free": ws.free / PHP, "locked": ws.locked / PHP, "balance": ws.balance / PHP,
                   "daily_left": ws.daily_remaining / PHP, "daily_cap": ws.daily_cap / PHP,
                   "per_deal_cap": ws.per_deal_cap / PHP, "paused": ws.paused, "underfunded": ws.underfunded,
                   "source": f"{network(t)['network']}, live"},
        "payees": payees, "pending_payee": {**pp.verdict.to_dict(), "card_text": pp.card} if pp else None,
        "now": ws.now, "deals": deals, "activity": [], "alerts": list(_alerts), "suppliers": None,
        "turns": [], "pending": pending, **network(t),
    }


def _attach_card(events: list[dict]) -> None:
    t = live()
    if t.pending:
        v = [e for e in events if e.get("event") == "verdict" and e["verdict"].get("needs_confirmation")]
        if v:
            v[-1]["card"] = fx.parse_card(t.pending.card)


def _remember_alerts(notes: list[str]) -> None:
    _alerts.clear()
    for n in notes:
        if m := fx.SHORT_RX.search(n):
            _alerts.append({"kind": "shortfall", "amount_php": fx._money(m[1]), "date": m[2], "text": n})
        elif n.startswith("HALTED"):
            _alerts.append({"kind": "halt", "text": n})


# ---------------------------------------------------------------- helpers


def _fixture(name: str) -> dict:
    if name not in fx.SPECS:
        raise HTTPException(404, f"unknown fixture {name!r}")
    return fx.build(name)


def _sse(kind: str, data) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------- API


@app.get("/api/fixtures")
def list_fixtures():
    return fx.names()


@app.get("/api/state")
def state(fixture: Optional[str] = Query(None)):
    return _fixture(fixture) if fixture else _live_state()


@app.post("/api/message")
async def message(m: Msg, fixture: Optional[str] = Query(None)):
    """SSE: one `step` per pipeline event as it happens, then one `reply`."""
    if fixture and m.text.strip().lower() in ("/guide", "/help", "help"):
        from tiwala_agent.core import GUIDE

        async def guide():
            yield _sse("reply", {"reply": GUIDE, "turn": {"user": m.text, "reply": GUIDE, "events": []}})
        return StreamingResponse(guide(), media_type="text/event-stream")
    if fixture:
        f = _fixture(fixture)
        last = f["turns"][-1] if f["turns"] else {"events": [], "reply": "Nothing to replay."}

        async def replay():
            for e in last["events"]:
                await asyncio.sleep(0.35)
                yield _sse("step", e)
            yield _sse("reply", {"reply": last["reply"], "turn": last})
        return StreamingResponse(replay(), media_type="text/event-stream")

    t = live()
    box: dict = {}

    def run():
        try:
            box["res"] = t.handle(m.text)
        except Exception as e:  # surface, never retry
            box["err"] = f"{type(e).__name__}: {e}"[:300]

    async def stream():
        th = threading.Thread(target=run, daemon=True)
        th.start()
        sent = 0
        while th.is_alive() or sent < len(t._events):
            evs = t._events  # core resets this list at the start of each turn
            while sent < len(evs):
                yield _sse("step", evs[sent])
                sent += 1
            await asyncio.sleep(0.15)
        if "err" in box:
            yield _sse("error", {"error": box["err"]})
            return
        res = box["res"]
        events = [dict(e) for e in res.events]
        _attach_card(events)
        yield _sse("reply", {"reply": fx.strip_card(res.reply), "turn": {
            "user": m.text, "reply": fx.strip_card(res.reply), "events": events}})
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/confirm")
def confirm(body: Optional[Confirm] = None, fixture: Optional[str] = Query(None)):
    """The owner's Confirm button sends their own "yes" (plus the 4 characters they typed, for a payee):
    the core matches it deterministically."""
    code = (body.code or "").strip() if body else ""
    text = f"yes {code}" if code else "yes"
    if fixture:
        f = _fixture(fx.CONFIRMS_TO.get(fixture, fixture))
        return {"turn": {**f["turns"][-1], "user": text}}
    res = live().handle(text)
    return {"turn": {"user": text, "reply": fx.strip_card(res.reply), "events": res.events}}


@app.post("/api/tick")
def tick(fixture: Optional[str] = Query(None)):
    if fixture:
        f = _fixture(fixture)
        return {"notes": [], "activity": f["activity"], "alerts": f["alerts"]}
    t = live()
    with t.turn_lock:
        t._events = []
        notes = t.tick()
    _remember_alerts(notes)
    return {"notes": notes, "events": t._events}


@app.get("/api/verify")
def verify(fixture: Optional[str] = Query(None)):
    from tiwala_agent.audit import AuditLog
    path = fx.AUDIT if fixture else Path(live().audit.path)
    log = AuditLog(path)
    return {"intact": log.verify(), "entries": len(log.entries()), "path": str(path.relative_to(fx.ROOT))}


from .negotiation_api import router as negotiation_router  # noqa: E402

_load_env()
authmod.install(app, _auth())

app.include_router(negotiation_router)


@app.on_event("startup")
def _warm():
    """Build the live agent and the negotiation view in the background, so the first page load is not a 10 s+
    chain read. Skipped with TIWALA_NO_WARM=1 (UI shots use fixtures only)."""
    if os.environ.get("TIWALA_NO_WARM") == "1":
        return
    from .negotiation_api import list_negotiations, start_telegram

    def run():
        try:
            list_negotiations(None)
            start_telegram()
        except Exception as e:  # no .env or RPC down: the request path reports it when someone asks
            print(f"warm-up skipped: {type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        return FileResponse(DIST / "index.html")
