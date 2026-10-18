"""Liquidity forecast across off-chain accounts and on-chain free balance. Pure, deterministic.

    H(t) = B_off + B_free + I(<=t) - O(<=t) - buffer

Open escrow is already excluded from B_free (the full PO is locked at creation), so
open deals need no further subtraction.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Flow:
    date: int  # unix day number (unix seconds // 86400)
    amount: int  # units, positive
    label: str


@dataclass
class Forecast:
    start: int
    points: list[tuple[int, int]]  # (day, H after that day's flows)
    shortfall_day: int | None
    shortfall: int  # units, positive when short

    @property
    def ok(self) -> bool:
        return self.shortfall_day is None


@dataclass
class Option:
    kind: str  # "delay" | "split" | "top_up"
    detail: str
    params: dict = field(default_factory=dict)


def project(
    b_off: int, b_free: int, inflows: list[Flow], outflows: list[Flow], buffer: int, today: int
) -> Forecast:
    days = sorted({today} | {f.date for f in inflows} | {f.date for f in outflows})
    h0 = b_off + b_free - buffer
    points, short_day, short = [], None, 0
    for d in days:
        h = (
            h0
            + sum(f.amount for f in inflows if f.date <= d)
            - sum(f.amount for f in outflows if f.date <= d)
        )
        points.append((d, h))
        if h < 0 and short_day is None:
            short_day, short = d, -h
    return Forecast(start=today, points=points, shortfall_day=short_day, shortfall=short)


def with_new_deal(
    b_off: int,
    b_free: int,
    inflows: list[Flow],
    planned: list[Flow],
    buffer: int,
    today: int,
    new_total: int,
    new_day: int,
    label: str = "new PO",
) -> Forecast:
    return project(b_off, b_free, inflows, planned + [Flow(new_day, new_total, label)], buffer, today)


def options(
    b_off: int,
    b_free: int,
    inflows: list[Flow],
    planned: list[Flow],
    buffer: int,
    today: int,
    new_total: int,
    new_day: int,
) -> list[Option]:
    """Deterministic candidate fixes for a shortfall. The Treasury planner ranks and explains them."""
    base = with_new_deal(b_off, b_free, inflows, planned, buffer, today, new_total, new_day)
    if base.ok:
        return []
    out: list[Option] = []
    # 1. delay: the earliest inflow day after which the new PO fits
    for f in sorted(inflows, key=lambda x: x.date):
        if f.date <= new_day:
            continue
        if with_new_deal(b_off, b_free, inflows, planned, buffer, today, new_total, f.date).ok:
            out.append(Option("delay", f"Place the PO on day {f.date} after '{f.label}' arrives", {"day": f.date}))
            break
    # 2. split: half now, half after the first inflow that covers it
    half = new_total // 2
    for f in sorted(inflows, key=lambda x: x.date):
        if f.date <= new_day:
            continue
        trial = project(
            b_off,
            b_free,
            inflows,
            planned + [Flow(new_day, half, "split 1"), Flow(f.date, new_total - half, "split 2")],
            buffer,
            today,
        )
        if trial.ok:
            out.append(
                Option(
                    "split",
                    f"Split into two deals: {half} units now, {new_total - half} units on day {f.date}",
                    {"first": half, "second": new_total - half, "second_day": f.date},
                )
            )
            break
    # 3. top up the wallet by the shortfall (owner moves fiat; the agent never does)
    out.append(Option("top_up", f"Top up the wallet by {base.shortfall} units before day {base.shortfall_day}",
                      {"amount": base.shortfall}))
    return out
