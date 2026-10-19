"""Seeding for scripts/local-demo.sh: a private local chain, demo data and a one-time login. No real keys or funds.

    python -m console.local_demo seed <deployment.json> <demo dir>
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

DAY = 86400


def seed(dep_path: Path, demo: Path) -> dict:
    from tiwala_agent.setup_data import write
    from tiwala_agent.supplier_agent import MandateStore, SupplierMandate
    from tiwala_agent.whatsapp import Contact, Contacts
    from web3 import Web3
    from .auth import hash_password

    dep = json.loads(dep_path.read_text())
    data = demo / "data"
    now = int(time.time())
    write(dep, data, now=now)
    sup = {n: Web3.to_checksum_address(a) for n, a in dep["suppliers"].items()}
    neg = data / "negotiation"
    # Lumen runs a simulated supplier agent with its own private mandate; Bayani answers in the WhatsApp simulator.
    MandateStore(neg / "supplier").put(SupplierMandate(sup["Lumen Textiles"], 150_00, 110_00, 450, 200,
                                                       now + 5 * DAY, 1500, [[400, 2000]]))
    Contacts(neg / "whatsapp").put(Contact(sup["Bayani Weaves"], f"sim:{sup['Bayani Weaves'].lower()}", "simulator",
                                           opted_in_at=now, opt_in_source="local demo simulator (not WhatsApp)"))
    password = secrets.token_urlsafe(12)
    login = demo / "login.txt"
    fd = os.open(login, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"username: demo\npassword: {password}\n")
    (demo / "env").write_text(f"TIWALA_ADMIN_USER=demo\nTIWALA_ADMIN_PASS_HASH={hash_password(password)}\n")
    return {"password": password, "suppliers": sup}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "seed":
        sys.exit(__doc__)
    out = seed(Path(sys.argv[2]), Path(sys.argv[3]))
    print(out["password"])
