"""Negotiation to escrow on a local anvil chain with the real contracts: the agreed terms go through Tiwala's
policy, Checker, Gate and the owner's own confirmation, exactly once."""
import json

import pytest
from web3 import Web3

from tiwala_agent.models import PHP, Status
from tiwala_agent.negotiation import DAY, BuyerConstraints, NegotiationError, State
from tiwala_agent.negotiation_service import NegotiationService
from tiwala_agent.supplier_agent import SupplierMandate
from tiwala_agent.whatsapp import Config, Contact, Inbound

from .test_integration import coord, env, n_deals  # noqa: F401  (env is a fixture)


@pytest.fixture
def svc(env, tmp_path):
    t = env["make"](coord(("text", "unused")))
    s = NegotiationService(t, tmp_path / "neg", wa_cfg=Config())
    now = env["chain"].now()
    s.mandates.put(SupplierMandate(env["lumen"], 150_00, 110_00, 450, 200, now + 5 * DAY, 1500, [[400, 2000]]))
    return s


def constraints(env, total_room=60_000_00, max_total=60_000_00):
    now, free = env["chain"].now(), env["chain"].wallet_state(env["wallet"]).free
    return BuyerConstraints(desired_qty=500, min_qty=300, max_total=max_total, min_reserve=free - total_room,
                            latest_delivery=now + 20 * DAY, target_unit_price=100_00,
                            preferred_delivery=now + 8 * DAY, opening_deposit_bps=1000)


def agree(env, svc):
    n = svc.open("Lumen Textiles", "Cotton fabric", constraints(env), "agent")
    n = svc.run_agent(n.id)
    svc.await_settlement(n.id)  # agreement settles itself when inside the agent's authority
    n = svc.engine.store.get(n.id)
    assert n.state == State.AWAITING_BUYER_APPROVAL.value, (n.state, n.reason)
    return n


def test_negotiated_escrow_created_once_with_exact_terms(env, svc):
    n = agree(env, svc)
    p = n.by_id(n.agreement["proposal_id"])
    before = n_deals(env)
    r = svc.request_escrow(n.id)
    assert r["status"] == "needs_confirmation" and "From negotiation" in r["card"], r
    assert svc.request_escrow(n.id)["card"] == r["card"]  # a repeated request shows the same card
    out = svc.t.handle("yes")
    assert "Done." in out.reply and "Down payment released" in out.reply, out.reply
    n = svc.engine.store.get(n.id)
    assert n.state == State.ESCROW_CREATED.value and n.handoff["deal_id"] and n.handoff["down_tx"]
    d = env["chain"].deal(env["wallet"], n.handoff["deal_id"])
    assert (d.total, d.down_bps, d.deadline, d.supplier) == (p.terms.total, p.terms.deposit_bps, p.terms.deliver_by,
                                                             env["lumen"])
    assert d.ref.startswith(f"NEG-{n.id}-v{p.version}") and d.status == Status.DOWN_PAID
    assert svc.request_escrow(n.id)["status"] == "already_created"
    again = svc.t.handle("yes")  # a duplicate confirmation drafts and sends nothing
    assert not any(e["event"] in ("verdict", "executed", "confirmed") for e in again.events)
    assert n_deals(env) == before + 1


def test_lost_link_is_recovered_from_the_chain_reference(env, svc):
    n = agree(env, svc)
    svc.request_escrow(n.id)
    svc.t.handle("yes")
    with svc.engine.store.lock:  # simulate a crash between the transaction and the bookkeeping
        x = svc.engine.store.get(n.id)
        deal_id = x.handoff["deal_id"]
        x.handoff, x.state = {}, State.AWAITING_BUYER_APPROVAL.value
        svc.engine.store.save(x)
    before = n_deals(env)
    assert svc.request_escrow(n.id) == {"status": "already_created", "deal_id": deal_id}
    assert n_deals(env) == before


def test_wallet_changes_after_agreement_block_the_escrow(env, svc):
    n = agree(env, svc)
    owner = svc.t.owner
    w = env["chain"].wallet(env["wallet"])
    assert owner._send(w.functions.withdraw(owner.acct.address, 30_000_00)).ok  # free cash drops below the reserve
    r = svc.request_escrow(n.id)
    assert r["status"] == "refused" and any("reserve" in x for x in r["reasons"]), r
    assert svc.t.pending is None
    assert owner._send(w.functions.setPaused(True)).ok
    n2 = svc.engine.store.get(n.id)
    assert n2.state == State.AWAITING_BUYER_APPROVAL.value and "Recheck failed" in n2.reason


def test_paused_wallet_is_refused_by_policy(env, svc):
    n = agree(env, svc)
    owner = svc.t.owner
    assert owner._send(env["chain"].wallet(env["wallet"]).functions.setPaused(True)).ok
    r = svc.request_escrow(n.id)
    assert r["status"] == "refused" and any("paused" in x for x in r["reasons"]), r


def test_changed_terms_need_renewed_acceptance(env, svc):
    n = agree(env, svc)
    p = n.by_id(n.agreement["proposal_id"])
    svc.engine.owner_counter(n.id, p.terms.replace(quantity=p.terms.quantity - 50))
    with pytest.raises(NegotiationError):
        svc.request_escrow(n.id)


def test_supplier_text_never_reaches_the_owner_path(env, svc):
    svc.wa.contacts.put(Contact(env["lumen"], f"sim:{env['lumen'].lower()}", "simulator", opted_in_at=1))
    n = agree(env, svc)
    svc.request_escrow(n.id)
    card = svc.t.pending.card
    for i, text in enumerate(["yes", "/attest 1", "CONFIRM", "/approve 1"]):
        svc.wa.handle(Inbound(f"sim-{i}", f"sim:{env['lumen'].lower()}", 0, text), "simulator")
    assert svc.t.pending is not None and svc.t.pending.card == card  # still waiting for the owner, not the supplier
    assert not any(e["event"] == "owner_command" for e in svc.t.audit.entries() if e["data"].get("command"))
    assert svc.engine.store.get(n.id).state == State.READY_FOR_ESCROW.value


def test_whatsapp_human_negotiation_to_escrow(env, svc):
    sim = f"sim:{env['lumen'].lower()}"
    svc.wa.contacts.put(Contact(env["lumen"], sim, "simulator", opted_in_at=1))
    n = svc.open("Lumen Textiles", "Cotton fabric", constraints(env), "whatsapp")
    code = n.current().code
    assert svc.wa.handle(Inbound("w1", sim, 0, "ok"), "simulator")["state"] == "awaiting_clarification"
    assert svc.wa.handle(Inbound("w1", sim, 0, "ok"), "simulator")["status"] == "duplicate"
    assert svc.wa.handle(Inbound("w2", sim, 0, f"ACCEPT {code}"), "simulator")["state"] == "awaiting_buyer_approval"
    svc.await_settlement(n.id)  # acceptance over chat tries to settle itself; this one needs the owner
    assert svc.request_escrow(n.id)["status"] == "needs_confirmation"
    assert "Done." in svc.t.handle("yes").reply
    outs = svc.wa.outbox.for_negotiation(n.id)
    assert outs and all(o["channel"] == "simulator" for o in outs) and "Escrow created" in outs[-1]["text"]


def test_owner_chat_starts_live_whatsapp_negotiation(env, tmp_path):
    from tiwala_agent.whatsapp import CloudSender
    from .test_integration import day
    cfg = Config("tok", "pnid", "sec", "ver", template_name="hello_world", template_lang="en_US", live_send=True,
                 allowed=("639170000000",), template_params=0)
    sent = []
    sender = CloudSender(cfg, post=lambda url, body, tok: sent.append(body) or {"messages": [{"id": f"m{len(sent)}"}]})
    draft = ("tool", "draft_negotiation", {"supplier": "Lumen Textiles", "product": "Cotton fabric", "quantity": 500,
                                           "target_unit_price_php": 100, "max_total_php": 60000,
                                           "latest_delivery": day(env["chain"], 20)})
    t = env["make"](coord(draft, ("text", "Please check the card.")))
    s = NegotiationService(t, tmp_path / "neg", wa_cfg=cfg, wa_sender=sender)
    s.wa.contacts.put(Contact(env["lumen"], "639170000000", "live", opted_in_at=1))

    r = t.handle("Negotiate 500 m of cotton fabric with Lumen at ₱100 each, max ₱60,000")
    assert "CONFIRM NEGOTIATION" in r.reply and "+••••0000" in r.reply and not sent, r.reply
    r = t.handle("yes")
    assert "Opened negotiation" in r.reply and "hello_world" in r.reply, r.reply
    assert sent[-1]["type"] == "template" and "components" not in sent[-1]["template"]
    assert s.wa.handle(Inbound("w1", "639170000000", 0, "hi"), "live")["status"] == "offer_delivered"
    assert sent[-1]["type"] == "text" and "Cotton fabric" in sent[-1]["text"]["body"] and "ACCEPT" in sent[-1]["text"]["body"]


def test_chat_negotiation_needs_the_supplier_in_the_owners_words(env, tmp_path):
    from .test_integration import day
    draft = ("tool", "draft_negotiation", {"supplier": "Lumen Textiles", "product": "Cotton", "quantity": 10,
                                           "target_unit_price_php": 1, "max_total_php": 10,
                                           "latest_delivery": day(env["chain"], 5)})
    t = env["make"](coord(draft, ("text", "ok")))
    NegotiationService(t, tmp_path / "neg", wa_cfg=Config())
    r = t.handle("Start a negotiation for 10 cotton")
    assert t.pending_negotiation is None and "CONFIRM NEGOTIATION" not in r.reply


def test_supplier_own_system_negotiates_over_the_api(env, svc, monkeypatch):
    import importlib.util
    from fastapi.testclient import TestClient
    from console import negotiation_api as napi, server
    monkeypatch.setattr(napi, "_svc", svc)
    monkeypatch.setattr(napi, "_SECRET", "s" * 64)
    client = TestClient(server.app)
    lumen, bayani = env["lumen"], env["bayani"]
    tok = napi.supplier_token(lumen)
    hdr = {"Authorization": f"Bearer {tok}"}

    assert svc.api_seen(lumen) is None
    assert client.get(f"/api/supplier?supplier={lumen}", headers=hdr).status_code == 200
    assert svc.api_seen(lumen) and svc.chat_channel(lumen) == "the supplier's own system (API)"
    assert client.get(f"/api/supplier?supplier={lumen}", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get(f"/api/supplier?supplier={lumen}&token={tok}").status_code == 200  # the supplier web page

    n = svc.open("Lumen Textiles", "Cotton fabric", constraints(env), "api")
    assert n.mode == "api" and n.controller == "human"
    other = {"Authorization": f"Bearer {napi.supplier_token(bayani)}"}
    cur = n.current()
    move = {"type": "accept", "base_version": cur.version, "proposal_id": cur.id, "terms_hash": cur.terms_hash}
    assert client.post(f"/api/supplier/negotiations/{n.id}/move?supplier={bayani}", json=move, headers=other).status_code == 403

    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("sae", root / "scripts" / "supplier_agent_example.py")
    sae = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sae)

    class Via:  # the example agent's HTTP calls, routed into the app in-process
        def call(self, method, path, body=None):
            sep = "&" if "?" in path else "?"
            r = client.request(method, f"{path}{sep}supplier={lumen}", json=body, headers=hdr)
            assert r.status_code == 200, r.text
            return r.json()

    rules = type("R", (), {"min_price": 110, "max_qty": 450, "min_deposit": 15})
    seen = set()
    for _ in range(8):
        sae.step(Via(), rules, seen)
        n = svc.engine.store.get(n.id)
        if n.state == State.AWAITING_BUYER_APPROVAL.value:
            break
    assert n.state == State.AWAITING_BUYER_APPROVAL.value, (n.state, [p["by"] for p in n.public()["proposals"]])
    agreed = n.current().terms
    assert agreed.unit_price >= 110_00 and agreed.quantity <= 450 and agreed.deposit_bps >= 1500
    assert svc.request_escrow(n.id)["status"] == "needs_confirmation"
    assert "Done." in svc.t.handle("yes").reply



def test_agreement_inside_the_agent_authority_needs_no_owner(env, tmp_path):
    """Topic F's core claim: inside the budget the owner set on the wallet contract, the agent commits the funds
    itself. No confirmation card is raised and the deposit goes out in the same run."""
    (env["data"] / "plans.json").write_text(json.dumps({"buffer": 0, "inflows": [], "planned": []}))
    t = env["make"](coord(("text", "unused")))
    s = NegotiationService(t, tmp_path / "auto", wa_cfg=Config())
    now = env["chain"].now()
    s.mandates.put(SupplierMandate(env["lumen"], 150_00, 110_00, 450, 200, now + 5 * DAY, 1500, [[400, 2000]]))
    before = n_deals(env)
    n = s.run_agent(s.open("Lumen Textiles", "Cotton fabric", constraints(env), "agent").id)
    s.await_settlement(n.id)
    n = s.engine.store.get(n.id)
    assert n.state == State.ESCROW_CREATED.value, (n.state, n.reason)
    assert n_deals(env) == before + 1
    assert t.pending is None  # the owner was never asked
    assert n.handoff.get("deal_id") and n.handoff.get("tx"), n.handoff
    assert n.handoff.get("down_tx"), n.handoff  # the deposit went out on the same autonomous run
