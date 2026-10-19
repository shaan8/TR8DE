"""Payee onboarding checks: deterministic rules run before a supplier is saved.

The Coordinator may draft a new payee from the owner's words. It never saves one: saving needs these checks,
the owner typing "yes" plus the address's last 4 characters, the owner key (addSupplier is onlyOwner), and
then the contract's supplierDelay before the first deal. Nothing the agent reads can become a payee.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3

from .models import SupplierEntry

_HEX = re.compile(r"0x[0-9a-fA-F]{40}")
EDGE = 4  # characters people check at each end of an address
# Characters that read alike in a supplier name, folded to one form (digits, Cyrillic and Greek lookalikes).
_FOLD = str.maketrans({"0": "o", "1": "l", "i": "l", "|": "l", "5": "s", "3": "e", "4": "a", "7": "t", "8": "b",
                       "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "l", "ѕ": "s",
                       "ο": "o", "α": "a", "ε": "e", "ι": "l", "κ": "k", "ν": "v", "ρ": "p", "τ": "t"})


@dataclass(frozen=True)
class Check:
    rule: str
    ok: bool
    detail: str
    severity: str = "refuse"  # refuse | flag

    def to_dict(self) -> dict:
        return {"rule": self.rule, "ok": self.ok, "detail": self.detail, "severity": self.severity}


@dataclass
class PayeeVerdict:
    name: str
    address: str  # checksummed when valid, else as given
    kind: str  # new | address_change
    replaces: Optional[str] = None  # old address for an address change
    checks: list[Check] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return all(c.ok or c.severity == "flag" for c in self.checks)

    @property
    def reasons(self) -> list[str]:
        return [c.detail for c in self.checks if not c.ok and c.severity == "refuse"]

    @property
    def flags(self) -> list[str]:
        return [c.rule for c in self.checks if not c.ok]

    def to_dict(self) -> dict:
        return {"name": self.name, "address": self.address, "kind": self.kind, "replaces": self.replaces,
                "allowed": self.allowed, "reasons": self.reasons, "flags": self.flags,
                "checks": [c.to_dict() for c in self.checks]}


def skeleton(name: str) -> str:
    """A name with accents, case, spacing, punctuation and lookalike characters folded away."""
    s = unicodedata.normalize("NFKD", name).casefold()
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("rn", "m").replace("vv", "w").translate(_FOLD)
    return re.sub(r"[^a-z0-9]", "", s)


def _plain(name: str) -> str:
    return " ".join(name.casefold().split())


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _poss(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def chunk(address: str) -> str:
    """0x1234 5678 ... for reading an address aloud on the card."""
    body = address[2:]
    return "0x" + " ".join(body[i:i + 4] for i in range(0, len(body), 4))


def check_payee(name: str, address: str, owner_texts: list[str], untrusted_texts: list[str],
                directory: dict[str, SupplierEntry], blocklist: set[str], reserved: dict[str, str]) -> PayeeVerdict:
    """Every rule runs, so the card can show all of them. `reserved` maps role -> address (wallet, owner, agent, token)."""
    name = " ".join((name or "").split())[:64]
    raw = (address or "").strip()
    said = " ".join(owner_texts)
    checks: list[Check] = []

    # 1. format and EIP-55 checksum: a mixed-case address with a bad checksum has a typo in it
    if not _HEX.fullmatch(raw):
        checks.append(Check("format", False, f"{raw or 'The address'} is not a 0x address of 40 hex characters."))
        return PayeeVerdict(name, raw, "new", checks=checks)
    mixed = raw[2:] != raw[2:].lower() and raw[2:] != raw[2:].upper()
    if mixed and not Web3.is_checksum_address(raw):
        checks.append(Check("checksum", False, "The address fails its checksum, so a character was likely "
                            "mistyped. Copy it again from the supplier's own invoice or message."))
    else:
        checks.append(Check("checksum", True, "Valid address" + (" with a matching checksum." if mixed else ".")))
    addr = Web3.to_checksum_address(raw)
    low = addr.lower()

    # 2. provenance: the address must be in the owner's own typed words, never only in chain or tool text
    typed = low in said.lower()
    in_chain = any(low in t.lower() for t in untrusted_texts)
    if typed:
        checks.append(Check("provenance", True, "You typed this address yourself."))
    else:
        where = "It appears only in text read from the chain" if in_chain else "TR8DE did not get it from you"
        checks.append(Check("provenance", False, f"You did not type this address. {where}, and nothing TR8DE reads "
                            "can become a payee. Paste it in your own message to save it."))
    if typed and in_chain:
        checks.append(Check("address_also_in_chain_text", False, "The same address also appears in a PO note on "
                            "the chain. Make sure it came from the supplier, not from that note.", "flag"))
    if name and _plain(name) not in _plain(said):
        checks.append(Check("name_filled_by_tiwala", False, f"You did not type the name '{name}'. Please check it.",
                            "flag"))

    # 3. never the wallet's own roles, never a blocklisted address
    role = next((r for r, a in reserved.items() if a and a.lower() == low), None)
    if low == "0x" + "0" * 40:
        role = "zero address"
    checks.append(Check("reserved", role is None, f"That is the {role} address, which cannot be a payee." if role
                        else "Not the wallet, owner, agent or token address."))
    listed = low in {b.lower() for b in blocklist}
    checks.append(Check("blocklist", not listed, "On the sanctions / blocklist." if listed else "Not on the blocklist."))

    # 4. one address, one supplier; a known name with a new address is a payout change
    kind, replaces = "new", None
    owner_of = directory.get(addr)
    same_name = next((e for e in directory.values() if _plain(e.name) == _plain(name)), None)
    if owner_of:
        checks.append(Check("duplicate", False, f"Already saved as {owner_of.name}." if _plain(owner_of.name) ==
                            _plain(name) else f"This address is already saved as {owner_of.name}."))
    elif same_name:
        kind, replaces = "address_change", same_name.address
        checks.append(Check("payout_address_change", False, f"{same_name.name} already has a saved payout address "
                            f"({same_name.address[:6]}...{same_name.address[-4:]}). A changed bank or wallet is the "
                            "most common invoice fraud: confirm it with the supplier by phone first. Deals with the "
                            "new address are flagged for 7 days.", "flag"))
    else:
        checks.append(Check("duplicate", True, "Not saved yet."))

    # 5. address poisoning: same first and last characters as a saved address, different middle
    look = next((e for a, e in directory.items() if a.lower() != low and a.lower()[2:2 + EDGE] == low[2:2 + EDGE]
                 and a.lower()[-EDGE:] == low[-EDGE:]), None)
    checks.append(Check("lookalike_address", look is None,
                        f"It starts with {addr[:2 + EDGE]} and ends with {addr[-EDGE:]} like {_poss(look.name)} saved "
                        f"address, but the middle differs. That is the address-poisoning pattern: a lookalike planted "
                        f"to be copied by mistake." if look else
                        f"No saved address shares its first and last {EDGE} characters."))

    # 6. lookalike names: same skeleton (Bayani Weave5, Lumen Textі1es) or one or two edits away
    sk = skeleton(name)
    twin = next((e for e in directory.values() if _plain(e.name) != _plain(name) and skeleton(e.name) == sk), None)
    near = next((e for e in directory.values() if _plain(e.name) != _plain(name) and e is not twin and len(sk) >= 6
                 and _distance(skeleton(e.name), sk) <= 2), None)
    if twin:
        checks.append(Check("lookalike_name", False, f"'{name}' reads the same as your saved supplier {twin.name} "
                            "but is spelled with different characters."))
    elif near:
        checks.append(Check("similar_name", False, f"'{name}' is close to your saved supplier {near.name}. Is this "
                            "a different business?", "flag"))
    else:
        checks.append(Check("lookalike_name", True, "Name does not imitate a saved supplier."))
    return PayeeVerdict(name, addr, kind, replaces, checks)
