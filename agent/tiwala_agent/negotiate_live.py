"""Live negotiation run for the record: Sepolia demo wallet, the configured models, stopping at the escrow card.

    cd agent && ../.venv/bin/python -m tiwala_agent.negotiate_live --deployment ../deployments/11155111.json

The supplier agent uses the live model unless TIWALA_SUPPLIER_AGENT=scripted; TIWALA_NEGOTIATOR=rules saves buyer-side
model calls. Nothing is confirmed: the escrow card is drafted and left for the owner. Writes
reports/negotiation/neg_live.{json,txt} with the validation level stated.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .audit import AuditLog
from .chain import Chain, OwnerConsole
from .core import Tiwala, _date, _parse_deadline
from .llm import from_env, negotiation_llms
from .models import PHP
from .negotiation import DAY, BuyerConstraints
from .negotiation_service import NegotiationService
from .supplier_agent import SupplierMandate

OUT = Path(__file__).resolve().parents[2] / "reports" / "negotiation"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deployment", required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--audit", default="logs/audit.jsonl")
    ap.add_argument("--supplier", default="Lumen Textiles")
    ap.add_argument("--escrow", action="store_true", help="also draft the escrow card (one Checker call)")
    args = ap.parse_args()

    dep = json.loads(Path(args.deployment).read_text())
    chain = Chain(os.environ["RPC_URL"], dep, os.environ["AGENT_PRIVATE_KEY"])
    owner = OwnerConsole(chain, dep["demoWallet"], os.environ["OWNER_PRIVATE_KEY"])
    t = Tiwala(chain, dep["demoWallet"], args.data, from_env(), AuditLog(args.audit), owner)
    m = negotiation_llms()
    s = NegotiationService(t, Path(args.data) / "negotiation", m["negotiator"], m["interpreter"], m["supplier"],
                           m["supplier_model"])
    addr = next(a for a, e in t.directory.items() if e.name == args.supplier)
    now = chain.now()
    eod = lambda days: _parse_deadline(_date(now + days * DAY))
    if s.mandates.get(addr) is None:
        s.mandates.put(SupplierMandate(addr, 150 * PHP, 110 * PHP, 450, 200, eod(5), 1500, [[400, 2000]]))
    free = chain.wallet_state(t.wallet).free
    c = BuyerConstraints(500, 300, 60_000 * PHP, min(100_000 * PHP, free - 65_000 * PHP), eod(20), 100 * PHP, eod(8), 1000)
    n = s.open(args.supplier, "Cotton fabric (metres)", c, "agent")
    n = s.run_agent(n.id)
    escrow = s.request_escrow(n.id) if args.escrow and n.state == "awaiting_buyer_approval" else None
    n = s.engine.store.get(n.id)

    sup_kind = n.agent_kind
    buyer_kind = "live model" if m["negotiator"] is not None else "rules-based"
    validation = f"live: Sepolia demo wallet reads, supplier agent {sup_kind}, {buyer_kind} buyer; escrow not confirmed"
    lines = [f"Live negotiation\nValidation: {validation}\n", f"NEG-{n.id} with {n.supplier_name}"]
    for msg in n.messages:
        who = "tiwala (buyer)" if msg["dir"] == "out" else f"supplier ({msg.get('via') or msg.get('channel')})"
        lines.append(f"{who}> {msg['text']}")
    lines.append(f"\nfinal state: {n.state}  {n.reason}")
    for p in n.props():
        lines.append(f"  v{p.version} {p.by:8} {p.terms.quantity} x {p.terms.unit_price / PHP:g} dep {p.terms.deposit_bps / 100:g}% "
                     f"source={p.source} status={p.status}")
    if escrow:
        lines.append(f"\nescrow request: {escrow['status']} {escrow.get('reasons', '')}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "neg_live.txt").write_text("\n".join(lines) + "\n")
    sup = s.supplier_dict(n)
    doc = {"meta": {"name": "neg_live", "title": "Live negotiation", "validation": validation},
           "buyer": s.buyer_dict(n), "supplier": {"supplier": addr, "name": n.supplier_name,
                                                   "mandate": sup.pop("mandate"), "negotiations": [sup]}, "after": {}}
    (OUT / "neg_live.json").write_text(json.dumps(doc, indent=1, default=str))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
