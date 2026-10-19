"""Network supplier reputation and down-payment cap. Pure, deterministic.

    w_j = v_j * beta_b          v_j = min(3, T_j / median_T_b(j)), then min(v_j, 1) for a success, max(v_j, 1) for a failure
    median_T_b(j) = median of buyer b's counted deals closed up to and including j (causal), so a later
    deal can never re-weight an earlier one and a failure can never raise R. The clamp stops a supplier from
    banking large successes while failing only small orders: size can make a failure count more, never less.
    p   = (s + a) / (n + a + b)  a = 1, b = 3
    d   = min(1, k_eff / 5)     R = d * p
    beta_b = 0.25 + 0.75 * min(1, h_b / 3)
    DP_cap = floor5%(DP_min + (DP_max - DP_min) * R), then the stranger cap.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from .models import ClosedDeal, Outcome

A_PRIOR = 1.0
B_PRIOR = 3.0
K_FULL = 5.0
VALUE_CAP = 3.0
BETA_FLOOR = 0.25
H_FULL = 3.0


@dataclass(frozen=True)
class DpPolicy:
    dp_min_bps: int = 1000
    dp_max_bps: int = 5000
    stranger_cap_bps: int = 2500
    contract_max_bps: int = 5000


@dataclass
class Reputation:
    supplier: str
    s: float
    n: float
    p: float
    k_eff: float
    d: float
    r: float
    on_time: int
    late: int
    non_delivery: int
    buyers: int
    betas: dict

    def summary(self) -> str:
        return (
            f"{self.on_time} on time, {self.late} late, {self.non_delivery} non-delivery "
            f"across {self.buyers} buyers (effective {self.k_eff:.2f}); score R = {self.r:.2f}"
        )


def _beta(h: int) -> float:
    return BETA_FLOOR + (1 - BETA_FLOOR) * min(1.0, h / H_FULL)


def buyer_betas(deals: list[ClosedDeal], supplier: str) -> dict[str, float]:
    """beta per buyer, from on-time completions with suppliers OTHER than `supplier`."""
    others: dict[str, set] = defaultdict(set)
    buyers = set()
    for c in deals:
        buyers.add(c.buyer)
        if c.outcome == Outcome.ON_TIME and c.supplier != supplier:
            others[c.buyer].add(c.supplier)
    return {b: _beta(len(others[b])) for b in buyers}


def score(deals: list[ClosedDeal], supplier: str) -> Reputation:
    counted = sorted((c for c in deals if c.outcome != Outcome.NEUTRAL), key=lambda c: c.order)
    seen: dict[str, list[int]] = defaultdict(list)
    v_of: list[float] = []
    for c in counted:
        seen[c.buyer].append(c.total)
        m = float(median(seen[c.buyer]))
        v_of.append(min(VALUE_CAP, c.total / m) if m > 0 else 0.0)

    betas = buyer_betas(deals, supplier)
    s = n = 0.0
    on_time = late = nd = 0
    good_buyers: set[str] = set()
    all_buyers: set[str] = set()
    for c, v in zip(counted, v_of):
        if c.supplier != supplier:
            continue
        all_buyers.add(c.buyer)
        beta = betas.get(c.buyer, BETA_FLOOR)
        w = (min(v, 1.0) if c.outcome == Outcome.ON_TIME else max(v, 1.0)) * beta
        if c.outcome == Outcome.ON_TIME:
            s += w
            n += w
            on_time += 1
            good_buyers.add(c.buyer)
        elif c.outcome == Outcome.LATE:
            n += w
            late += 1
        elif c.outcome == Outcome.NON_DELIVERY:
            n += 2 * w
            nd += 1

    p = (s + A_PRIOR) / (n + A_PRIOR + B_PRIOR)
    k_eff = sum(betas.get(b, BETA_FLOOR) for b in good_buyers)
    d = min(1.0, k_eff / K_FULL)
    return Reputation(
        supplier=supplier,
        s=s,
        n=n,
        p=p,
        k_eff=k_eff,
        d=d,
        r=d * p,
        on_time=on_time,
        late=late,
        non_delivery=nd,
        buyers=len(all_buyers),
        betas={b: betas[b] for b in all_buyers},
    )


@dataclass
class DpCap:
    cap_bps: int
    network_cap_bps: int
    stranger: bool
    reason: str


def dp_cap(rep: Reputation, buyer: str, deals: list[ClosedDeal], policy: DpPolicy = DpPolicy()) -> DpCap:
    raw = policy.dp_min_bps + (policy.dp_max_bps - policy.dp_min_bps) * rep.r
    network = int(raw // 500) * 500
    network = min(network, policy.contract_max_bps)
    known = any(c.buyer == buyer and c.supplier == rep.supplier and c.outcome == Outcome.ON_TIME for c in deals)
    cap = network if known else min(network, policy.stranger_cap_bps)
    reason = f"{rep.summary()}, so the network cap is {network / 100:.0f}%"
    if not known and cap < network:
        reason += f"; new to you, so held to the {policy.stranger_cap_bps / 100:.0f}% stranger cap"
    elif not known:
        reason += " (new to you; stranger cap does not bind)"
    return DpCap(cap_bps=cap, network_cap_bps=network, stranger=not known, reason=reason)
