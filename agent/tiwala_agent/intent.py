"""Intent verifier: deterministic diff between a drafted action and what the user actually said.

The request ledger holds only user-authored chat text for the current draft. Values the
user stated must match the action (the latest mention wins, so corrections work). Values
the user did not state are listed as agent-filled and shown on the confirmation card.
Monitor actions must match the rule that fired them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Action, ActionKind, Deal, PHP

_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b|pct\b)", re.I)
_AMT = re.compile(r"(?:₱|\bphp\s?|\bp(?=\d))\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k\b)?|\b(\d[\d,]*(?:\.\d+)?)\s*(k)\b", re.I)
_PO = re.compile(r"\bpo[\s#-]*(\d{1,6})\b", re.I)
_ADDR = re.compile(r"0x[0-9a-fA-F]{40}")


@dataclass
class Parsed:
    percents: list[float] = field(default_factory=list)  # in order of mention
    amounts: list[int] = field(default_factory=list)  # units
    pos: list[str] = field(default_factory=list)  # normalized "PO-104"
    suppliers: list[str] = field(default_factory=list)  # names, in order of mention
    addresses: list[str] = field(default_factory=list)


def parse(texts: list[str], supplier_names: list[str]) -> Parsed:
    p = Parsed()
    for t in texts:
        p.percents += [float(x) for x in _PCT.findall(t)]
        for m in _AMT.finditer(t):
            num, k1, num2, k2 = m.groups()
            raw = num or num2
            val = float(raw.replace(",", ""))
            if k1 or k2:
                val *= 1000
            p.amounts.append(round(val * PHP))
        p.pos += [f"PO-{int(x)}" for x in _PO.findall(t)]
        low = t.lower()
        hits = sorted(
            ((low.find(tok), n) for n in supplier_names for tok in _name_tokens(n) if tok in low),
            key=lambda x: x[0],
        )
        for _, n in hits:
            if n not in p.suppliers:
                p.suppliers.append(n)
        p.addresses += _ADDR.findall(t)
    return p


def _name_tokens(name: str) -> list[str]:
    full = name.lower()
    first = full.split()[0]
    return [full] if len(first) < 4 else [full, first]


def _norm_ref(ref: str | None) -> str | None:
    if not ref:
        return None
    m = _PO.search(ref)
    return f"PO-{int(m.group(1))}" if m else ref.strip()


@dataclass
class IntentResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)
    agent_filled: list[str] = field(default_factory=list)


def verify(
    action: Action,
    request_texts: list[str],
    supplier_names_by_addr: dict[str, str],
    deal: Deal | None = None,
    agreement: dict | None = None,
) -> IntentResult:
    if action.origin.kind == "monitor":
        return _verify_monitor(action)
    if action.origin.kind == "negotiation":
        return _verify_negotiation(action, agreement, deal)

    parsed = parse(request_texts, list(supplier_names_by_addr.values()))
    mm: list[str] = []
    filled: list[str] = []

    supplier = action.supplier or (deal.supplier if deal else None)
    name = supplier_names_by_addr.get(supplier or "", None)
    if parsed.suppliers:
        if name not in parsed.suppliers:
            mm.append(f"supplier: you named {', '.join(parsed.suppliers)}, action pays {name or supplier}")
    elif action.kind == ActionKind.CREATE_DEAL:
        filled.append("supplier")
    if parsed.addresses and supplier and supplier.lower() not in [a.lower() for a in parsed.addresses]:
        mm.append("payee address differs from the address in your message")

    bps = action.down_bps if action.down_bps is not None else (deal.down_bps if deal else None)
    if parsed.percents and bps is not None:
        want = round(parsed.percents[-1] * 100)
        if want != bps:
            mm.append(f"down payment: you said {parsed.percents[-1]:g}%, action uses {bps / 100:g}%")
    elif action.kind == ActionKind.CREATE_DEAL:
        filled.append("down payment %")

    total = action.total if action.total is not None else (deal.total if deal else None)
    if parsed.amounts and total is not None:
        down = total * (bps or 0) // 10_000
        if not any(a in (total, down, total - down) for a in parsed.amounts):
            mm.append(
                f"amount: you mentioned {', '.join(f'{a / PHP:,.2f}' for a in parsed.amounts)}, "
                f"action is {total / PHP:,.2f} total"
            )
    elif action.kind == ActionKind.CREATE_DEAL:
        filled.append("total")

    ref = _norm_ref(action.ref if action.kind == ActionKind.CREATE_DEAL else (deal.ref if deal else None))
    if parsed.pos:
        if ref not in parsed.pos:
            mm.append(f"PO: you named {', '.join(parsed.pos)}, action is for {ref or 'an unnamed PO'}")
    elif action.kind == ActionKind.CREATE_DEAL:
        filled.append("PO reference")

    if action.kind == ActionKind.CREATE_DEAL:
        filled.append("deadline")
    return IntentResult(ok=not mm, mismatches=mm, agent_filled=filled)


def _verify_negotiation(action: Action, agreement: dict | None, deal: Deal | None = None) -> IntentResult:
    """A negotiated deal must carry exactly the agreed terms: payee, total, deposit, deadline and reference."""
    if not agreement:
        return IntentResult(False, ["no agreement on record for this negotiation"])
    mm = []
    if action.kind == ActionKind.RELEASE_DOWN:  # only the agreed deposit of the deal this agreement created
        if deal is None:
            return IntentResult(False, ["deal not found"])
        for f, dv in (("supplier", deal.supplier), ("total", deal.total), ("down_bps", deal.down_bps), ("ref", deal.ref)):
            if dv != agreement.get(f):
                mm.append(f"deal {deal.id} {f.replace('_', ' ')} is {dv}, agreement has {agreement.get(f)}")
        return IntentResult(ok=not mm, mismatches=mm)
    for f in ("supplier", "total", "down_bps", "deadline", "ref"):
        if getattr(action, f) != agreement.get(f):
            mm.append(f"{f.replace('_', ' ')}: agreed {agreement.get(f)}, action uses {getattr(action, f)}")
    return IntentResult(ok=not mm, mismatches=mm)


def _verify_monitor(action: Action) -> IntentResult:
    """origin.detail = '<rule>:<deal_id>'. Each rule may fire exactly one action kind on one deal."""
    allowed = {"overdue_cancel": ActionKind.CANCEL, "attested_release": ActionKind.RELEASE_BALANCE}
    try:
        rule, deal_s = action.origin.detail.split(":", 1)
        deal_id = int(deal_s)
    except ValueError:
        return IntentResult(False, [f"unparseable monitor rule '{action.origin.detail}'"])
    mm = []
    if allowed.get(rule) != action.kind:
        mm.append(f"rule {rule} cannot fire {action.kind.value}")
    if action.deal_id != deal_id:
        mm.append(f"rule fired for deal {deal_id}, action targets deal {action.deal_id}")
    return IntentResult(ok=not mm, mismatches=mm)
