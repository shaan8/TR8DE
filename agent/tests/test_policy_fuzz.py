"""Seeded fuzzing of the policy engine: random wallets, deals, payees, origins and checker/intent results.
After every decision, the rules below must hold for anything the policy allows. A mutation check shows the
fuzzer catches each rule when it is deliberately broken."""
import random

import pytest

from tiwala_agent import policy as P
from tiwala_agent.models import MONEY_MOVING, Action, ActionKind, Deal, Origin, Status, SupplierEntry, WalletState
from tiwala_agent.reputation import DpCap

SEED, N = 20261019, 200_000
SUP = [f"0x{i:040x}" for i in range(1, 6)]


def case(rng: random.Random):
    now = 1_800_000_000
    per_deal = rng.choice([50_000_00, 200_000_00])
    daily = rng.choice([0, 30_000_00, 150_000_00])
    spent = rng.randint(0, daily) if daily else 0
    free = rng.choice([0, 10_000_00, 500_000_00])
    w = WalletState("0xw", "0xo", "0xa", rng.random() < 0.1, rng.random() < 0.05, free + 1, 1, free, per_deal, daily,
                    150_000_00, rng.choice([0, 2000, 5000]), 600, spent, now // 86400, now)
    sup = rng.choice(SUP)
    listed = {s: rng.random() < 0.8 for s in SUP}
    active = {s: now + rng.choice([-1, 0, 3600]) for s in SUP}
    block = {s for s in SUP if rng.random() < 0.15}
    directory = {s: SupplierEntry(f"S{i}", s, 0) for i, s in enumerate(SUP) if rng.random() < 0.9}
    kind = rng.choice(list(ActionKind))
    origin = Origin(rng.choice(["user", "monitor", "negotiation", "contract"]), "x", rng.random() < 0.05)
    deal = Deal("0xw", 7, sup, rng.choice([1_000_00, 40_000_00, 160_000_00]), rng.choice([0, 1000, 5000]),
                now + rng.choice([-7200, 3600]), 0, rng.choice(list(Status)), rng.random() < 0.8)
    a = Action(kind, origin, supplier=sup if kind == ActionKind.CREATE_DEAL else None,
               total=rng.choice([0, 5_000_00, 60_000_00, 300_000_00]) if kind == ActionKind.CREATE_DEAL else None,
               down_bps=rng.choice([0, 1000, 3000, 6000]) if kind == ActionKind.CREATE_DEAL else None,
               deadline=now + rng.choice([-10, 86400]) if kind == ActionKind.CREATE_DEAL else None,
               deal_id=None if kind == ActionKind.CREATE_DEAL else rng.choice([7, 7, 7, 8]))
    ctx = P.PolicyContext(w, directory, listed, active, block, deal=deal,
                          cap=DpCap(rng.choice([1000, 2500, 5000]), 5000, False, "r") if rng.random() < 0.9 else None,
                          open_exposure=rng.choice([0, 250_000_00]), checker_approved=rng.choice([True, True, False, None]),
                          intent_mismatches=[] if rng.random() < 0.85 else ["x"])
    return a, ctx


def violations(a: Action, ctx: P.PolicyContext, v) -> list[str]:
    if not v.allowed or a.kind not in MONEY_MOVING:
        return []
    w, d, out = ctx.wallet, ctx.deal, []
    payee = a.supplier if a.kind == ActionKind.CREATE_DEAL else d.supplier
    rules = {
        "halted wallet": w.paused or w.underfunded,
        "no checker approval": ctx.checker_approved is not True,
        "intent mismatch": bool(ctx.intent_mismatches),
        "bad origin": a.origin.kind not in ("user", "monitor", "negotiation") or a.origin.from_contract_text,
        "monitor out of scope": a.origin.kind == "monitor" and a.kind not in (ActionKind.CANCEL, ActionKind.RELEASE_BALANCE),
        "negotiation out of scope": a.origin.kind == "negotiation" and a.kind not in (ActionKind.CREATE_DEAL, ActionKind.RELEASE_DOWN),
    }
    if a.kind != ActionKind.CANCEL:
        rules["blocklisted payee"] = payee in ctx.blocklist
        rules["payee in cooling"] = ctx.onchain_listed.get(payee, False) and ctx.onchain_active_at.get(payee, 0) > w.now
    if a.kind in (ActionKind.CREATE_DEAL, ActionKind.RELEASE_DOWN):
        rules["payee not listed"] = not ctx.onchain_listed.get(payee, False)
    if a.kind == ActionKind.RELEASE_BALANCE:
        rules["removed payee without owner"] = not ctx.onchain_listed.get(payee, False) and not v.needs_confirmation
    if a.kind != ActionKind.CREATE_DEAL:
        rules["wrong deal"] = d.id != a.deal_id
    if a.kind == ActionKind.CREATE_DEAL:
        rules |= {"no confirmation on create": not v.needs_confirmation,
                  "over per-deal cap": not 0 < a.total <= w.per_deal_cap, "over free balance": a.total > w.free,
                  "over contract down cap": a.down_bps > w.max_down_bps,
                  "over reputation cap": ctx.cap is None or a.down_bps > ctx.cap.cap_bps,
                  "past deadline": a.deadline <= w.now, "exposure cap": ctx.open_exposure + a.total > P.PolicySettings().supplier_exposure_cap,
                  "unregistered payee": a.supplier not in ctx.directory}
    if a.kind == ActionKind.RELEASE_DOWN:
        rules |= {"not locked": d.status != Status.LOCKED, "not approved": not d.owner_approved,
                  "over daily limit": d.down_amount > w.daily_remaining}
    if a.kind == ActionKind.RELEASE_BALANCE:
        rules |= {"not attested": d.status != Status.DELIVERED, "over daily limit": d.total - d.down_amount > w.daily_remaining}
    if a.kind == ActionKind.CANCEL:
        rules |= {"cancel not cancellable": d.status not in (Status.LOCKED, Status.DOWN_PAID),
                  "cancel before grace": w.now <= d.deadline + w.grace,
                  "user cancel unconfirmed": a.origin.kind == "user" and not v.needs_confirmation}
    return [k for k, bad in rules.items() if bad]


def run(n=N, seed=SEED):
    rng, broken, allowed = random.Random(seed), {}, {}
    for _ in range(n):
        a, ctx = case(rng)
        v = P.decide(a, ctx)
        if v.allowed:
            allowed[a.kind.value] = allowed.get(a.kind.value, 0) + 1
        for r in violations(a, ctx, v):
            broken[r] = broken.get(r, 0) + 1
    return broken, allowed


def test_policy_holds_every_rule_on_200k_random_cases():
    broken, allowed = run()
    assert broken == {}, broken
    assert all(allowed.get(k.value, 0) > 100 for k in MONEY_MOVING), allowed  # the fuzzer reaches every allowed path


@pytest.mark.parametrize("mutation,rule", [
    ("skip_payout_checks", "blocklisted payee"),
    ("skip_daily_limit", "over daily limit"),
    ("skip_checker", "no checker approval"),
])
def test_fuzzer_catches_deliberate_bugs(monkeypatch, mutation, rule):
    if mutation == "skip_payout_checks":
        monkeypatch.setattr(P, "_payout_checks", lambda *a, **k: None)
    elif mutation == "skip_daily_limit":
        real = P._check_release_down
        monkeypatch.setattr(P, "_check_release_down", lambda a, ctx, r, f: real(
            a, P.PolicyContext(**{**ctx.__dict__, "wallet": _rich(ctx.wallet)}), r, f))
    else:
        real = P.decide
        monkeypatch.setattr(P, "decide", lambda a, ctx, s=P.PolicySettings(): real(
            a, P.PolicyContext(**{**ctx.__dict__, "checker_approved": True}), s))
    broken, _ = run(n=20_000)
    assert broken.get(rule), broken


def _rich(w: WalletState) -> WalletState:
    return WalletState(**{**w.__dict__, "daily_cap": 10 ** 15, "spent_today": 0})
