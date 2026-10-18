#!/usr/bin/env python3
"""Build Sepolia tx-hash evidence tables from Foundry broadcasts.
Usage: python3 scripts/evidence_table.py  ->  reports/sepolia-evidence.md"""
import json, glob, collections
ES = "https://sepolia.etherscan.io"
dep = json.load(open("deployments/11155111.json"))
names = {dep["token"].lower(): "tPHP", dep["factory"].lower(): "Factory",
         dep["demoWallet"].lower(): "Demo wallet", dep["owner"].lower(): "Owner",
         dep["agent"].lower(): "Agent"}
for i, w in enumerate(dep["networkWallets"], 1): names[w.lower()] = f"Buyer {i} wallet"
for n, a in dep["suppliers"].items(): names[a.lower()] = n
nm = lambda a: names.get((a or "").lower(), (a or "")[:10])
link = lambda h, t=None: f"[{t or h[:10]+'...'}]({ES}/tx/{h})"
addr = lambda a: f"[`{a[:8]}...{a[-4:]}`]({ES}/address/{a})"

out = ["# Tiwala on Sepolia: on-chain evidence", "",
       f"Chain 11155111, start block {dep['startBlock']}. All links open on Sepolia Etherscan.", "",
       "## Contracts", "", "| Role | Address |", "|---|---|"]
for k, r in [("token","tPHP settlement token"),("factory","TiwalaFactory"),("demoWallet","Demo agent wallet"),("owner","Owner (human)"),("agent","Agent key")]:
    out.append(f"| {r} | {addr(dep[k])} |")
for n, a in dep["suppliers"].items(): out.append(f"| Supplier: {n} | {addr(a)} |")
for i, w in enumerate(dep["networkWallets"], 1): out.append(f"| Network buyer {i} | {addr(w)} |")

rows, summ = [], collections.OrderedDict()
for f in sorted(glob.glob("broadcast/*/11155111/run-latest.json")):
    d = json.load(open(f)); script = f.split("/")[1].replace(".s.sol", "")
    rc = {r["transactionHash"]: r for r in d.get("receipts", [])}
    for t in d["transactions"]:
        h = t.get("hash") or ""; r = rc.get(h, {})
        fn = (t.get("function") or ("deploy " + (t.get("contractName") or "")) if t["transactionType"].startswith("CREATE") else (t.get("function") or "transfer/call")).split("(")[0]
        to = t.get("contractAddress") if t["transactionType"].startswith("CREATE") else t["transaction"].get("to")
        ok = {"0x1": "ok", "0x0": "REVERT"}.get(r.get("status"), "pending")
        blk = int(r["blockNumber"], 16) if r.get("blockNumber") else ""
        gas = int(r["gasUsed"], 16) if r.get("gasUsed") else ""
        rows.append((script, fn, nm(to), h, blk, gas, ok))
        s = summ.setdefault((script, fn), [0, h]); s[0] += 1

out += ["", "## Transactions by action", "", "| Script | Action | Count | First tx |", "|---|---|---|---|"]
out += [f"| {s} | `{f}` | {c} | {link(h) if h else '-'} |" for (s, f), (c, h) in summ.items()]
out += ["", f"## Full log ({len(rows)} txs, {sum(r[6]=='ok' for r in rows)} confirmed ok, {sum(r[6]=='REVERT' for r in rows)} reverted)", "",
        "| # | Script | Action | Target | Tx | Block | Gas | Status |", "|---|---|---|---|---|---|---|---|"]
out += [f"| {i} | {s} | `{f}` | {to} | {link(h) if h else '-'} | {b} | {g} | {ok} |" for i, (s, f, to, h, b, g, ok) in enumerate(rows, 1)]
open("reports/sepolia-evidence.md", "w").write("\n".join(out) + "\n")
print(f"{len(rows)} txs -> reports/sepolia-evidence.md")
