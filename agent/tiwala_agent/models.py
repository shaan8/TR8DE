"""Shared data types. Amounts are integer token units (centavos, 2 decimals)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum
from typing import Optional

PHP = 100  # token units per peso


def php(units: int) -> str:
    return f"₱{units / PHP:,.2f}"


class Status(IntEnum):
    NONE = 0
    LOCKED = 1
    DOWN_PAID = 2
    DELIVERED = 3
    COMPLETED = 4
    REFUNDED = 5
    DISPUTED = 6


class Outcome(str, Enum):
    ON_TIME = "on_time"
    LATE = "late"  # delivered after deadline: counts 1x
    NON_DELIVERY = "non_delivery"  # cancel after DP, or dispute refunded: counts 2x
    NEUTRAL = "neutral"  # cancel before DP, dispute released: not counted


class Tier(IntEnum):
    READ = 0
    AUTONOMOUS = 1
    CONFIRM = 2
    REFUSE = 3


class ActionKind(str, Enum):
    CREATE_DEAL = "create_deal"
    RELEASE_DOWN = "release_down_payment"
    RELEASE_BALANCE = "release_balance"
    CANCEL = "cancel_deal"


MONEY_MOVING = {ActionKind.CREATE_DEAL, ActionKind.RELEASE_DOWN, ActionKind.RELEASE_BALANCE, ActionKind.CANCEL}


@dataclass(frozen=True)
class Origin:
    """Where an action came from. Only 'user' and 'monitor' may originate actions."""

    kind: str  # "user" | "monitor"
    detail: str  # the user's literal request text, or the monitor rule id
    from_contract_text: bool = False  # True if any field was taken from contract free text


@dataclass
class Action:
    kind: ActionKind
    origin: Origin
    supplier: Optional[str] = None  # checksum address
    total: Optional[int] = None  # units
    down_bps: Optional[int] = None
    deadline: Optional[int] = None  # unix seconds
    ref: Optional[str] = None
    deal_id: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class Deal:
    wallet: str
    id: int
    supplier: str
    total: int
    down_bps: int
    deadline: int
    delivered_at: int
    status: Status
    owner_approved: bool
    ref: str = ""  # untrusted free text from DealCreated

    @property
    def down_amount(self) -> int:
        return self.total * self.down_bps // 10_000

    @property
    def unpaid(self) -> int:
        if self.status == Status.LOCKED:
            return self.total
        if self.status in (Status.DOWN_PAID, Status.DELIVERED, Status.DISPUTED):
            return self.total - self.down_amount
        return 0


@dataclass
class ClosedDeal:
    """One closed deal as the reputation scorer sees it."""

    buyer: str  # buyer wallet address
    supplier: str
    total: int
    outcome: Outcome
    order: tuple = (0, 0)  # (block, log index) of the closing event; sorts deals by when they closed


@dataclass
class WalletState:
    address: str
    owner: str
    agent: str
    paused: bool
    underfunded: bool
    balance: int
    locked: int
    free: int
    per_deal_cap: int
    daily_cap: int
    approval_threshold: int
    max_down_bps: int
    grace: int
    spent_today: int
    current_day: int
    now: int

    @property
    def daily_remaining(self) -> int:
        spent = self.spent_today if self.current_day == self.now // 86400 else 0
        return max(0, self.daily_cap - spent)


@dataclass
class SupplierEntry:
    """Off-chain supplier directory entry (registered payout address)."""

    name: str
    address: str
    address_changed_at: int = 0  # unix seconds; 0 = since onboarding


@dataclass
class Verdict:
    tier: Tier
    allowed: bool  # False = refused
    needs_confirmation: bool
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tier": int(self.tier),
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
            "reasons": self.reasons,
            "flags": self.flags,
        }
