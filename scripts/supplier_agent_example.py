#!/usr/bin/env python3
"""Example supplier-side agent: the supplier's own system negotiating with a TR8DE buyer over the supplier API.
Standard library only. Replace decide() with your own pricing logic or model.

    python3 scripts/supplier_agent_example.py --url http://127.0.0.1:8000 \
        --supplier 0xSupplierAddress --min-price 110 --max-qty 450 --min-deposit 15

The token comes from the buyer (`python -m console.supplier_token "<payee name>"`) and is read from the
TIWALA_SUPPLIER_TOKEN environment variable, so it never appears in your shell history or process list.
It goes in an `Authorization: Bearer` header, never in a URL. See docs/supplier-api.md.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

OPEN_FOR_SUPPLIER = {"awaiting_acceptance", "awaiting_clarification"}


class Api:
    def __init__(self, url, supplier, token):
        self.url, self.supplier, self.token = url.rstrip("/"), supplier, token

    def call(self, method, path, body=None):
        sep = "&" if "?" in path else "?"
        req = urllib.request.Request(f"{self.url}{path}{sep}supplier={self.supplier}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = json.loads(e.read() or b"{}").get("detail", e.reason)
            raise RuntimeError(f"{method} {path}: {e.code} {detail}") from None


def decide(offer, rules):
    """Accept the buyer's terms if they meet our floor; otherwise counter once per buyer version."""
    t = offer["terms"]
    price, qty, dep = t["unit_price"] / 100, t["quantity"], t["deposit_bps"] / 100
    if price >= rules.min_price and qty <= rules.max_qty and dep >= rules.min_deposit:
        return {"type": "accept"}
    counter_price = max(price, round(rules.min_price * 1.05, 2))
    return {"type": "counter", "terms": {
        "quantity": min(qty, rules.max_qty), "unit_price_php": counter_price,
        "deposit_pct": max(dep, rules.min_deposit),
        "deliver_by": str(t["deliver_by"]),  # keep the buyer's exact deadline (unix seconds)
        "note": f"We can do {counter_price:,.2f} per unit with a {max(dep, rules.min_deposit):g}% deposit."}}


def step(api, rules, seen):
    home = api.call("GET", "/api/supplier")
    for n in home["negotiations"]:
        if n["mode"] != "api" or n["state"] not in OPEN_FOR_SUPPLIER:
            continue
        offer = next((p for p in reversed(n["proposals"]) if p["status"] == "open"), None)
        if offer is None or offer["by"] != "buyer" or (n["id"], offer["version"]) in seen:
            continue
        seen.add((n["id"], offer["version"]))
        move = decide(offer, rules)
        move.update(base_version=offer["version"], proposal_id=offer["id"], terms_hash=offer["terms_hash"])
        out = api.call("POST", f"/api/supplier/negotiations/{n['id']}/move", move)
        t = offer["terms"]
        print(f"{n['id']} v{offer['version']}: buyer offered {t['quantity']} x {t['unit_price'] / 100:,.2f}, "
              f"{t['deposit_bps'] / 100:g}% deposit -> {move['type']}; now {out['state']}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Example supplier agent for the TR8DE supplier API.")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--supplier", required=True, help="your payout address as saved by the buyer")
    ap.add_argument("--min-price", type=float, required=True, help="lowest unit price you accept, PHP")
    ap.add_argument("--max-qty", type=int, required=True, help="most units you can deliver")
    ap.add_argument("--min-deposit", type=float, default=0, help="lowest deposit you accept, percent")
    ap.add_argument("--interval", type=float, default=5, help="seconds between checks")
    ap.add_argument("--once", action="store_true", help="check once and exit")
    rules = ap.parse_args()
    token = os.environ.get("TIWALA_SUPPLIER_TOKEN", "")
    if not token:
        sys.exit("Set TIWALA_SUPPLIER_TOKEN to the token the buyer gave you.")
    api = Api(rules.url, rules.supplier, token)
    try:
        home = api.call("GET", "/api/supplier")
    except (RuntimeError, urllib.error.URLError) as e:
        sys.exit(f"Cannot connect: {e}")
    print(f"Connected as {home['name']} ({rules.supplier}). Waiting for offers; Ctrl+C to stop.", flush=True)
    seen = set()
    while True:
        try:
            step(api, rules, seen)
        except (RuntimeError, urllib.error.URLError) as e:
            print(f"warning: {e}", file=sys.stderr, flush=True)
        if rules.once:
            return
        time.sleep(rules.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
