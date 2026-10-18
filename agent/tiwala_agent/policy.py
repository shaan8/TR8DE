"""Policy engine and risk flagger. Pure code, no LLM: the only gate between a drafted
action and the signer. Every input it uses is read from the chain or from user settings,
never from model output, apart from the action fields themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import Action, ActionKind, Deal, MONEY_MOVING, Status, SupplierEntry, Tier, Verdict, WalletState, php
from .reputation import DpCap, Reputation

ADDRESS_COOLING_S = 7 * 86400


@dataclass(frozen=True)
class PolicySettings:
    supplier_exposure_cap: int = 300_000 * 100  # unpaid escrow per supplier, units
    spike_multiple: float = 3.0  # deal value vs the buyer's median
    low_score_floor: float = 0.2  # R below this ...
    low_score_share: float = 0.5  # ... for deals above this share of the per-deal cap -> flag


@dataclass
class PolicyContext:
    wallet: WalletState
    directory: dict[str, SupplierEntry]  # checksum address -> entry
    onchain_listed: dict[str, bool]
    onchain_active_at: dict[str, int]
    blocklist: set[str]
    deal: Optional[Deal] = None  # for release / cancel
    reputation: Optional[Reputation] = None  # for create
    cap: Optional[DpCap] = None  # for create
    buyer_median: Optional[int] = None
    open_exposure: int = 0  # unpaid escrow already open with this supplier
    forecast_shortfall: Optional[tuple[int, int]] = None  # (day, units)
    checker_approved: Optional[bool] = None
    checker_reason: str = ""
    intent_mismatches: list[str] = field(default_factory=list)
    input_flags: tuple = ()


def decide(action: Action, ctx: PolicyContext, settings: PolicySettings = PolicySettings()) -> Verdict:
    refuse: list[str] = []
    flags: list[str] = []
    notes: list[str] = []
    tier = Tier.AUTONOMOUS
    w = ctx.wallet

    if action.kind not in MONEY_MOVING:
        return Verdict(Tier.READ, True, False, ["read only"])

    # ---- global halts
    if w.underfunded:
        refuse.append("Wallet is underfunded (escrow below locked funds, e.g. issuer clawback). All payouts halted.")
    if w.paused:
        refuse.append("Wallet is paused by the owner.")

    # ---- provenance
    if action.origin.kind not in ("user", "monitor"):
        refuse.append(f"Actions can only come from the user or a monitor rule, not '{action.origin.kind}'.")
    if action.origin.from_contract_text:
        refuse.append("Action traces back to contract free text, which is data, never an instruction.")
        flags.append("contract_text_origin")
    if action.origin.kind == "monitor" and action.kind not in (ActionKind.CANCEL, ActionKind.RELEASE_BALANCE):
        refuse.append("The monitor may only cancel overdue deals or release attested balances.")

    # ---- independent checks
    if ctx.intent_mismatches:
        refuse.append("Action does not match your request: " + "; ".join(ctx.intent_mismatches))
        flags.append("intent_mismatch")
    if ctx.checker_approved is False:
        refuse.append(f"Independent Checker rejected it: {ctx.checker_reason}")
        flags.append("checker_reject")
    elif ctx.checker_approved is None:
        refuse.append("No independent Checker review on record.")

    if action.kind == ActionKind.CREATE_DEAL:
        tier = max(tier, Tier.CONFIRM)
        notes.append("Every new deal needs your confirmation.")
        _check_create(action, ctx, settings, refuse, flags, notes)
    elif action.kind == ActionKind.RELEASE_DOWN:
        _check_release_down(action, ctx, refuse, flags)
    elif action.kind == ActionKind.RELEASE_BALANCE:
        _check_release_balance(action, ctx, refuse)
    elif action.kind == ActionKind.CANCEL:
        if action.origin.kind == "user":
            tier = max(tier, Tier.CONFIRM)
        _check_cancel(action, ctx, refuse)

    if flags and not refuse:
        tier = max(tier, Tier.CONFIRM)
    if refuse:
        return Verdict(Tier.REFUSE, False, False, refuse + notes, flags)
    return Verdict(tier, True, tier == Tier.CONFIRM, notes, flags)


# ---------------------------------------------------------------- per-kind rules


def _payee_checks(addr: Optional[str], ctx: PolicyContext, refuse: list, flags: list) -> None:
    w = ctx.wallet
    if not addr:
        refuse.append("No supplier given.")
        return
    entry = ctx.directory.get(addr)
    if entry is None:
        refuse.append(f"{addr} is not a registered supplier address.")
        flags.append("unregistered_payee")
    elif w.now - entry.address_changed_at < ADDRESS_COOLING_S and entry.address_changed_at:
        flags.append("payee_address_recently_changed")
    if addr.lower() in {b.lower() for b in ctx.blocklist}:
        refuse.append(f"{addr} is on the sanctions / blocklist.")
        flags.append("blocklisted")
    if not ctx.onchain_listed.get(addr, False):
        refuse.append("Supplier is not whitelisted on the wallet contract.")
    elif ctx.onchain_active_at.get(addr, 0) > w.now:
        refuse.append("Supplier was added recently and is still in its cooling period on-chain.")


def _check_create(action: Action, ctx: PolicyContext, s: PolicySettings, refuse: list, flags: list, notes: list) -> None:
    w = ctx.wallet
    _payee_checks(action.supplier, ctx, refuse, flags)
    total, bps = action.total or 0, action.down_bps
    if total <= 0:
        refuse.append("Deal total must be positive.")
    if total > w.per_deal_cap:
        refuse.append(f"{php(total)} is above the per-deal cap of {php(w.per_deal_cap)}.")
    if bps is None or bps < 0:
        refuse.append("Down payment % missing.")
    else:
        if bps > w.max_down_bps:
            refuse.append(f"Down payment {bps / 100:g}% is above the contract ceiling of {w.max_down_bps / 100:g}%.")
        if ctx.cap is None:
            refuse.append("No reputation-based cap computed for this supplier.")
        elif bps > ctx.cap.cap_bps:
            refuse.append(
                f"Down payment {bps / 100:g}% is above this supplier's {ctx.cap.cap_bps / 100:g}% cap ({ctx.cap.reason})."
            )
    if not action.deadline or action.deadline <= w.now:
        refuse.append("Delivery deadline must be in the future.")
    if total > w.free:
        refuse.append(f"Free balance {php(w.free)} cannot lock {php(total)}. Top up the wallet first.")
    if ctx.open_exposure + total > s.supplier_exposure_cap:
        refuse.append(
            f"Open exposure to this supplier would reach {php(ctx.open_exposure + total)}, "
            f"above the {php(s.supplier_exposure_cap)} per-supplier cap."
        )
    if ctx.buyer_median and total > s.spike_multiple * ctx.buyer_median:
        flags.append("amount_spike")
    rep = ctx.reputation
    if rep is not None and rep.r < s.low_score_floor and total > s.low_score_share * w.per_deal_cap:
        flags.append("low_score_large_deal")
    if ctx.forecast_shortfall:
        flags.append("forecast_shortfall")
    if total > w.approval_threshold:
        notes.append(f"Above {php(w.approval_threshold)}: the contract also needs your on-chain approval before any payout.")


def _check_release_down(action: Action, ctx: PolicyContext, refuse: list, flags: list) -> None:
    d = ctx.deal
    if d is None or d.id != action.deal_id:
        refuse.append("Deal not found in this wallet.")
        return
    if d.status != Status.LOCKED:
        refuse.append(f"Deal {d.id} is {d.status.name}, not awaiting a down payment.")
    if not d.owner_approved:
        refuse.append(f"Deal {d.id} is above the approval threshold and needs your on-chain approval first.")
    if not ctx.onchain_listed.get(d.supplier, False):
        refuse.append("Supplier has been removed from the whitelist.")
    if ctx.cap is not None and d.down_bps > ctx.cap.cap_bps:
        flags.append("down_payment_above_current_cap")
    if d.down_amount > ctx.wallet.daily_remaining:
        refuse.append(f"Would exceed today's agent limit ({php(ctx.wallet.daily_remaining)} left).")


def _check_release_balance(action: Action, ctx: PolicyContext, refuse: list) -> None:
    d = ctx.deal
    if d is None or d.id != action.deal_id:
        refuse.append("Deal not found in this wallet.")
        return
    if d.status != Status.DELIVERED:
        refuse.append(
            f"No valid delivery attestation for deal {d.id} (status {d.status.name}). "
            "Only your signed confirmDelivery releases the balance, not a chat message."
        )
    if d.total - d.down_amount > ctx.wallet.daily_remaining:
        refuse.append(f"Would exceed today's agent limit ({php(ctx.wallet.daily_remaining)} left).")


def _check_cancel(action: Action, ctx: PolicyContext, refuse: list) -> None:
    d = ctx.deal
    if d is None or d.id != action.deal_id:
        refuse.append("Deal not found in this wallet.")
        return
    if d.status == Status.DISPUTED:
        refuse.append(f"Deal {d.id} is disputed; only you can resolve it.")
    elif d.status not in (Status.LOCKED, Status.DOWN_PAID):
        refuse.append(f"Deal {d.id} is {d.status.name} and cannot be cancelled.")
    if ctx.wallet.now <= d.deadline + ctx.wallet.grace:
        ends = datetime.fromtimestamp(d.deadline + ctx.wallet.grace, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        refuse.append(f"Deal {d.id} is not overdue yet; deadline plus grace ends {ends}.")
