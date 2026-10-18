"""Off-chain inputs: supplier directory, user plans and the sanctions/blocklist. All read-only;
the agent never moves fiat."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from web3 import Web3

from .forecast import Flow
from .models import SupplierEntry


@dataclass
class Plans:
    inflows: list[Flow] = field(default_factory=list)  # expected receivables
    planned: list[Flow] = field(default_factory=list)  # POs the owner plans to place
    buffer: int = 0


def load_plans(path: Path) -> Plans:
    if not path.exists():
        return Plans()
    j = json.loads(path.read_text())
    return Plans(
        inflows=[Flow(int(f["day"]), int(f["amount"]), f["label"]) for f in j.get("inflows", [])],
        planned=[Flow(int(f["day"]), int(f["amount"]), f["label"]) for f in j.get("planned", [])],
        buffer=int(j.get("buffer", 0)),
    )


def load_directory(path: Path) -> dict[str, SupplierEntry]:
    j = json.loads(path.read_text())
    out = {}
    for e in j:
        addr = Web3.to_checksum_address(e["address"])
        out[addr] = SupplierEntry(e["name"], addr, int(e.get("address_changed_at", 0)))
    return out


def load_blocklist(path: Path) -> set[str]:
    return set(json.loads(path.read_text())) if path.exists() else set()
