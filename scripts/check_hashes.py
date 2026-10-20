#!/usr/bin/env python3
"""Check every Sepolia transaction hash in a Markdown file against the chain. Standard library only.

    python3 scripts/check_hashes.py [docs/submission/6-execution-evidence.md]

Prints signer, function selector, block and status for each hash. RPC: SEPOLIA_RPC_URL, else a public node.
Exits non-zero if a hash is not found on chain.
"""
import json
import os
import re
import sys
import urllib.request

RPC = os.environ.get("SEPOLIA_RPC_URL") or "https://ethereum-sepolia-rpc.publicnode.com"
NAMES = {"0x42ffa87e": "createDeal", "0xe5890b85": "releaseDownPayment", "0xfd84cb97": "confirmDelivery",
         "0x76079be3": "releaseBalance", "0x31ea1a39": "cancelDeal", "0x17df4745": "addSupplier",
         "0x40c10f19": "mint", "0x32d6fdb8": "createWallet", "0x26c9162d": "setLimits"}


def rpc(method, params):
    req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "tr8de-check"})
    return json.load(urllib.request.urlopen(req, timeout=30)).get("result")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/submission/6-execution-evidence.md"
    hashes = list(dict.fromkeys(h.lower() for h in re.findall(r"/tx/(0x[0-9a-fA-F]{64})", open(path).read())))
    missing = 0
    for h in hashes:
        tx, rc = rpc("eth_getTransactionByHash", [h]), rpc("eth_getTransactionReceipt", [h])
        if not tx or not rc:
            print(f"{h}  NOT FOUND")
            missing += 1
            continue
        fn = "deploy" if tx["to"] is None else NAMES.get(tx["input"][:10], tx["input"][:10])
        status = "ok" if int(rc["status"], 16) else "reverted"
        print(f"{h}  from {tx['from'][:10]}  {fn:<19} block {int(tx['blockNumber'], 16)}  {status}")
    print(f"{len(hashes) - missing}/{len(hashes)} found on Sepolia")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
