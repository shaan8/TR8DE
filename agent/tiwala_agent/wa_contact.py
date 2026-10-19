"""Owner-only: link a saved payee to a real WhatsApp number, recording how consent was collected.

    python -m tiwala_agent.wa_contact "John the fruit guy" 639270269627 --consent "agreed by phone 2026-10-19"

If WHATSAPP_ALLOWED_RECIPIENTS is set, the number must be in it. This writes a local contact record only; it sends nothing.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from .data import load_directory
from .whatsapp import Config, Contact, Contacts

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("supplier", help="saved payee name")
    ap.add_argument("number", help="WhatsApp number with country code, digits only")
    ap.add_argument("--consent", required=True, help="how the supplier agreed to WhatsApp messages")
    ap.add_argument("--data", default=str(ROOT / "agent" / "data"))
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT / "agent"))
    from console.server import _load_env
    _load_env()
    wa = re.sub(r"\D", "", a.number)
    allowed = Config.from_env().allowed
    if allowed and wa not in allowed:
        print(f"{wa} is not in WHATSAPP_ALLOWED_RECIPIENTS; add it to .env first.")
        return 1
    hits = [(addr, e) for addr, e in load_directory(Path(a.data) / "suppliers.json").items()
            if e.name.lower() == a.supplier.lower()]
    if len(hits) != 1:
        print(f"No single saved payee named {a.supplier!r}.")
        return 1
    addr = hits[0][0]
    Contacts(Path(a.data) / "negotiation" / "whatsapp").put(
        Contact(addr, wa, "live", opted_in_at=int(time.time()), opt_in_source=a.consent[:200]))
    print(f"Linked {hits[0][1].name} ({addr}) to WhatsApp +••••{wa[-4:]}. Restart the console to pick it up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
