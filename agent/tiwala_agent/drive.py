"""Non-interactive CLI: feeds messages to one Tiwala session, for recorded live runs.

    python3 -m tiwala_agent.drive --deployment ../deployments/11155111.json "msg 1" "yes" "/tick"
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
    ap.add_argument("messages", nargs="+")
    args = ap.parse_args()

    dep = json.loads(Path(args.deployment).read_text())
    chain = Chain(os.environ["RPC_URL"], dep, os.environ["AGENT_PRIVATE_KEY"])
    owner = OwnerConsole(chain, dep["demoWallet"], os.environ["OWNER_PRIVATE_KEY"])
    audit = AuditLog(args.audit)
    t = Tiwala(chain, dep["demoWallet"], args.data, from_env(), audit, owner)
    for msg in args.messages:
        print(f"\nyou> {msg}")
        if msg == "/tick":
            print("\n".join(t.tick()) or "Monitor: nothing to do.")
        else:
            print("tiwala> " + t.handle(msg).reply, flush=True)
    print("\naudit chain intact" if audit.verify() else "\nAUDIT CHAIN BROKEN")


if __name__ == "__main__":
    main()
