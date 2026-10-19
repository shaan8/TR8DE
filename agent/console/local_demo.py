"""Seeding for scripts/local-demo.sh: a private local chain, demo data and a one-time login. No real keys or funds.

    python -m console.local_demo seed <deployment.json> <demo dir>
    python -m console.local_demo suppliers <deployment.json> <data dir>   # live.sh: simulated supplier side only
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

DAY = 86400


def seed_suppliers(dep: dict, data: Path, now: int) -> dict:
    """The simulated supplier side, labelled as such everywhere: Lumen runs a supplier agent with its own private
    mandate, Bayani answers in the local WhatsApp simulator. Never replaces a mandate or contact already on file."""
    from tiwala_agent.supplier_agent import MandateStore, SupplierMandate
    from tiwala_agent.whatsapp import Contact, Contacts
    from web3 import Web3
    sup = {n: Web3.to_checksum_address(a) for n, a in dep["suppliers"].items()}
    neg = data / "negotiation"
    mandates, contacts = MandateStore(neg / "supplier"), Contacts(neg / "whatsapp")
    if "Lumen Textiles" in sup and mandates.get(sup["Lumen Textiles"]) is None:
        mandates.put(SupplierMandate(sup["Lumen Textiles"], 150_00, 110_00, 450, 200, now + 5 * DAY, 1500,
                                     [[400, 2000]]))
    if "Bayani Weaves" in sup and contacts.get(sup["Bayani Weaves"]) is None:
        contacts.put(Contact(sup["Bayani Weaves"], f"sim:{sup['Bayani Weaves'].lower()}", "simulator",
                             opted_in_at=now, opt_in_source="local demo simulator (not WhatsApp)"))
    return sup


def seed(dep_path: Path, demo: Path) -> dict:
    from tiwala_agent.setup_data import write
    from .auth import hash_password

    dep = json.loads(dep_path.read_text())
    data = demo / "data"
    now = int(time.time())
    write(dep, data, now=now)
    sup = seed_suppliers(dep, data, now)
    password = secrets.token_urlsafe(12)
    login = demo / "login.txt"
    fd = os.open(login, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"username: demo\npassword: {password}\n")
    # Single-quoted: the scrypt hash contains "$", which a shell must not expand when it sources this file.
    (demo / "env").write_text(f"TIWALA_ADMIN_USER='demo'\nTIWALA_ADMIN_PASS_HASH='{hash_password(password)}'\n")
    return {"password": password, "suppliers": sup}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("seed", "suppliers"):
        sys.exit(__doc__)
    if sys.argv[1] == "suppliers":
        seed_suppliers(json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3]), int(time.time()))
    else:
        print(seed(Path(sys.argv[2]), Path(sys.argv[3]))["password"])
