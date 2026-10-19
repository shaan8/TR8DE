#!/usr/bin/env python3
"""Verify a TR8DE audit log offline. Standard library only; no TR8DE install or server needed.

    python3 scripts/verify_audit.py agent/logs/audit.jsonl
    python3 scripts/verify_audit.py agent/logs/audit.jsonl --anchors agent/logs/anchors.jsonl \
        --rpc https://ethereum-sepolia-rpc.publicnode.com

Checks:
  1. Hash chain: every entry's hash covers its body and the previous hash (detects edits and removals mid-log).
  2. Anchors: for each on-chain anchor (count, head), the log still has entry `count` with that hash
     (detects deleting the tail or rewriting the whole chain). With --rpc, each anchor is read from the
     transaction on-chain rather than trusted from the local anchors file.
Exit status 0 only if every check passes.
"""
import argparse
import hashlib
import json
import sys
import urllib.request

PREFIX = b"TIWALA-AUDIT-v1"


def chain_ok(entries):
    prev = "0" * 64
    for i, e in enumerate(entries, 1):
        body = {k: v for k, v in e.items() if k != "hash"}
        if body.get("prev") != prev:
            return f"entry {i}: previous-hash link broken"
        if hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() != e.get("hash"):
            return f"entry {i}: content does not match its hash"
        prev = e["hash"]
    return ""


def rpc(url, method, params):
    req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "tiwala-verify"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["result"]


def onchain_anchor(url, tx):
    t = rpc(url, "eth_getTransactionByHash", [tx])
    if t is None:
        return None, "transaction not found"
    rcpt = rpc(url, "eth_getTransactionReceipt", [tx])
    if not rcpt or rcpt.get("status") != "0x1":
        return None, "transaction failed or not mined"
    data = bytes.fromhex(t["input"][2:])
    if not data.startswith(PREFIX) or len(data) != len(PREFIX) + 40:
        return None, "transaction is not a TR8DE audit anchor"
    rest = data[len(PREFIX):]
    return (int.from_bytes(rest[:8], "big"), rest[8:].hex(), t["from"]), ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify a TR8DE audit log.")
    ap.add_argument("log")
    ap.add_argument("--anchors", help="anchors.jsonl written by /anchor")
    ap.add_argument("--rpc", help="JSON-RPC URL to read each anchor from the chain")
    ap.add_argument("--owner", help="expected anchor signer address (optional)")
    a = ap.parse_args(argv)

    with open(a.log) as f:
        entries = [json.loads(l) for l in f if l.strip()]
    bad = chain_ok(entries)
    print(f"hash chain: {len(entries)} entries, " + ("FAIL: " + bad if bad else "intact"))
    failed = bool(bad)

    if a.anchors:
        with open(a.anchors) as f:
            anchors = [json.loads(l) for l in f if l.strip()]
        for an in anchors:
            count, head, who = an["count"], an["head"], an.get("owner", "?")
            src = "local file"
            if a.rpc:
                got, err = onchain_anchor(a.rpc, an["tx"])
                if err:
                    print(f"anchor {an['tx'][:12]}…: FAIL: {err}")
                    failed = True
                    continue
                count, head, who = got
                src = "on-chain"
            if a.owner and who.lower() != a.owner.lower():
                print(f"anchor {an['tx'][:12]}…: FAIL: signed by {who}, expected {a.owner}")
                failed = True
                continue
            if len(entries) < count:
                msg = f"FAIL: log has {len(entries)} entries, anchor recorded {count} (entries deleted)"
            elif entries[count - 1].get("hash") != head:
                msg = f"FAIL: entry {count} does not match its anchor (log rewritten)"
            else:
                msg = f"ok at entry {count}"
            failed |= msg.startswith("FAIL")
            print(f"anchor {an['tx'][:12]}… ({src}): {msg}")
        if not anchors:
            print("anchors: none recorded; deleting the end of the log would not be detected")
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
