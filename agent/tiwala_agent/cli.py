"""Chat REPL for the demo.

    export RPC_URL=... AGENT_PRIVATE_KEY=... OWNER_PRIVATE_KEY=... ANTHROPIC_API_KEY=...
    python -m tiwala_agent.cli --deployment ../deployments/11155111.json --data data/

Commands: /tick (run the monitor now), /attest N, /approve N, /dispute N,
/resolve N release|refund, /verify (check the audit chain), /quit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .audit import AuditLog
from .chain import Chain, OwnerConsole
from .core import Tiwala
from .llm import from_env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deployment", required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--audit", default="logs/audit.jsonl")
    args = ap.parse_args()

    dep = json.loads(Path(args.deployment).read_text())
    chain = Chain(os.environ["RPC_URL"], dep, os.environ["AGENT_PRIVATE_KEY"])
    owner = OwnerConsole(chain, dep["demoWallet"], os.environ["OWNER_PRIVATE_KEY"]) \
        if os.environ.get("OWNER_PRIVATE_KEY") else None
    audit = AuditLog(args.audit)
    t = Tiwala(chain, dep["demoWallet"], args.data, from_env(), audit, owner)
    print("TR8DE ready. Wallet", dep["demoWallet"])
    while True:
        try:
            msg = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/tick":
            print("\n".join(t.tick()) or "Monitor: nothing to do.")
            continue
        if msg == "/verify":
            print("audit chain intact" if audit.verify() else "AUDIT CHAIN BROKEN")
            continue
        print("\ntiwala> " + t.handle(msg).reply)


if __name__ == "__main__":
    main()
