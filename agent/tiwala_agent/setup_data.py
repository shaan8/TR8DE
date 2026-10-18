"""Write the demo data directory from a deployment file:
suppliers.json (registered payout addresses), plans.json (receivables and planned POs), blocklist.json.
Off-chain balances are not seeded: they come only from accounts linked in the UI (connectors.py).

    python -m tiwala_agent.setup_data ../deployments/11155111.json data/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ATTACKER = "0x000000000000000000000000000000000000ABcD"


def write(deployment: dict, out: Path, now: int | None = None) -> None:
    now = now or int(time.time())
    today = now // 86400
    out.mkdir(parents=True, exist_ok=True)
    sup = [{"name": n, "address": a, "address_changed_at": 0} for n, a in deployment["suppliers"].items()]
    (out / "suppliers.json").write_text(json.dumps(sup, indent=2))
    plans = {
        "buffer": 20_000_00,
        "inflows": [{"day": today + 24, "amount": 90_000_00, "label": "Receivable from SM store"}],
        "planned": [{"day": today + 7, "amount": 150_000_00, "label": "Planned PO: holiday stock"},
                    {"day": today + 14, "amount": 80_000_00, "label": "Planned PO: packaging"}],
    }
    (out / "plans.json").write_text(json.dumps(plans, indent=2))
    (out / "blocklist.json").write_text(json.dumps([ATTACKER]))


if __name__ == "__main__":
    write(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
    print("wrote", sys.argv[2])
