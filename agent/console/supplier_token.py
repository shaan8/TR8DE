"""Owner-only: print the API token for one saved payee, to hand to that supplier's own system.

    cd agent && ../.venv/bin/python -m console.supplier_token "Lumen Textiles"

The token lets that supplier (and only that supplier) read its own negotiations and answer offers. It cannot see
your limits, move money or act for another supplier. Send it over a private channel. To revoke every supplier
token, delete agent/data/supplier_token_secret and restart the console.
"""
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 1
    from tiwala_agent.data import load_directory
    from .negotiation_api import supplier_token
    from .server import HERE, _load_env
    _load_env()
    data = Path(os.environ.get("TIWALA_DATA", str(HERE.parents[1] / "agent" / "data")))
    hits = [(a, e) for a, e in load_directory(data / "suppliers.json").items() if e.name.lower() == argv[0].lower()]
    if len(hits) != 1:
        print(f"No single saved payee named {argv[0]!r}. Saved payees: "
              + ", ".join(e.name for e in load_directory(data / "suppliers.json").values()))
        return 1
    addr, e = hits[0]
    print(f"Supplier: {e.name}\nAddress:  {addr}\nToken:    {supplier_token(addr)}\n")
    print("Give the supplier the address and token privately. Their system calls the supplier API with\n"
          "`Authorization: Bearer <token>`; see docs/supplier-api.md. Example agent:\n"
          f"  TIWALA_SUPPLIER_TOKEN=<token> python3 scripts/supplier_agent_example.py --supplier {addr} "
          "--min-price 110 --max-qty 450 --min-deposit 15")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
