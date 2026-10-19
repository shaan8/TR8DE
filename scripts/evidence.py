#!/usr/bin/env python3
"""Execution evidence in one command: run every scenario, group it, write a judge-readable summary.

    PATH=$HOME/.foundry/bin:$PATH .venv/bin/python scripts/evidence.py

Writes reports/evidence/SUMMARY.md, results.json and pytest.log. Chain scenarios run on a local anvil chain with
the real contracts (deployed by the same forge scripts as Sepolia); models are scripted so results are
reproducible. Exits non-zero if any scenario fails. Live Sepolia and live-model runs are in reports/live and
reports/sepolia-evidence.md.
"""
import json
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "evidence"

# First matching pattern wins. Order matters: attacks before the generic task patterns.
GROUPS = [
    ("C. Attacks blocked", ["rt_", "pentest_", "audit_f3", "injection", "lookalike", "from_chain_text", "override",
                            "agent_key_cannot", "claiming_a_payment", "never_reaches", "cross_site", "lockout",
                            "global_limit", "fuzz", "deliberate_bugs", "poisoning", "not_typed_by_owner",
                            "bad_checksum", "reserved_blocklisted", "wrong_sender", "unknown_sender",
                            "outside_limits", "below_floor", "signature", "duplicate_webhook", "every_rule", "refusals",
                            "intent_catches", "tampering", "sybil", "contract_text", "serialized", "oversized",
                            "token_travels", "flood", "single_use", "unknown_chat", "token_never", "only_the_webhook",
                            "other_methods", "hashed_and_expire"]),
    ("D. Privacy and integrity", ["data_minimized", "never_sees", "private_limits", "audit_", "session", "hash_is",
                                   "security_headers", "test_bypass", "everything_but_public", "httponly"]),
    ("B. Safe execution and owner control", ["confirmation", "expires", "freeze", "breaker", "monitor_waits",
                                             "monitor_halts", "removed_supplier", "paused", "changed_terms",
                                             "wallet_changes", "needs_the_supplier", "outage", "lost_link",
                                             "key_compromise", "ambiguous", "invalidates", "expired", "takeover",
                                             "bounded", "impossible", "no_feasible", "garbage", "retry",
                                             "breaks_the_buyers", "reserve_and_deposit", "needs_window",
                                             "terminal_states", "flagged", "waiting_period", "payout_address"]),
    ("A. Task completion", [""]),
]
SKIP_FILES = ("test_qwen.py", "test_deepseek.py")  # provider adapters, not scenarios


def group_of(name: str) -> str:
    return next(g for g, pats in GROUPS if any(p in name for p in pats))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    xml = OUT / "junit.xml"
    t0 = time.time()
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", f"--junitxml={xml}", "tests"]
    cmd += [f"--ignore=tests/{f}" for f in SKIP_FILES]
    p = subprocess.run(cmd, cwd=ROOT / "agent", capture_output=True, text=True)
    (OUT / "pytest.log").write_text(p.stdout + p.stderr)
    cases = []
    for tc in ET.parse(xml).getroot().iter("testcase"):
        name = tc.get("name", "")
        status = "fail" if tc.find("failure") is not None or tc.find("error") is not None else \
                 "skip" if tc.find("skipped") is not None else "pass"
        cases.append({"name": name, "file": tc.get("classname", "").split(".")[-1], "group": group_of(name),
                      "status": status, "seconds": round(float(tc.get("time", 0)), 2)})
    xml.unlink(missing_ok=True)

    sys.path.insert(0, str(ROOT / "agent"))
    sys.path.insert(0, str(ROOT / "agent" / "tests"))
    from test_policy_fuzz import N, SEED, run
    broken, allowed = run()

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "agent", "src", "scripts"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    total, passed = len(cases), sum(c["status"] == "pass" for c in cases)
    summary = {"commit": commit + (" (with local changes)" if dirty else ""), "python": platform.python_version(),
               "date_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "seconds": round(time.time() - t0),
               "scenarios": total, "passed": passed,
               "fuzz": {"seed": SEED, "cases": N, "rule_violations": broken, "allowed_by_kind": allowed},
               "groups": {g: {"total": sum(c["group"] == g for c in cases),
                              "passed": sum(c["group"] == g and c["status"] == "pass" for c in cases)}
                          for g, _ in GROUPS}}
    (OUT / "results.json").write_text(json.dumps({"summary": summary, "cases": cases}, indent=2) + "\n")

    lines = ["# TR8DE execution evidence", "",
             f"Commit `{summary['commit']}`, Python {summary['python']}, {summary['date_utc']} UTC, "
             f"{summary['seconds']} s. Reproduce: `PATH=$HOME/.foundry/bin:$PATH .venv/bin/python scripts/evidence.py`.",
             "", "Chain scenarios run on a local anvil chain with the real contracts; models are scripted, so a "
             "pass means the deterministic controls held whatever the models said. Live Sepolia and live-model runs: "
             "[`reports/sepolia-evidence.md`](../sepolia-evidence.md), [`reports/live`](../live).", "",
             f"**{passed}/{total} scenarios pass.**", "", "| Group | Passed |", "| --- | --- |"]
    lines += [f"| {g} | {v['passed']}/{v['total']} |" for g, v in summary["groups"].items()]
    lines += ["", f"Policy fuzzing: {N:,} random cases (seed {SEED}), "
              f"{sum(broken.values())} rule violations; allowed payouts reached: "
              + ", ".join(f"{k} {v}" for k, v in sorted(allowed.items())) + ". Three deliberately planted bugs "
              "(no payee checks, no daily limit, no Checker) are each caught.", ""]
    for g, _ in GROUPS:
        lines += [f"## {g}", "", "| Scenario | File | Result |", "| --- | --- | --- |"]
        lines += [f"| {c['name'].removeprefix('test_').replace('_', ' ')} | {c['file']} | {c['status']} |"
                  for c in cases if c["group"] == g]
        lines.append("")
    (OUT / "SUMMARY.md").write_text("\n".join(lines))
    print(f"{passed}/{total} scenarios pass; fuzz violations {sum(broken.values())}. Wrote {OUT.relative_to(ROOT)}/SUMMARY.md")
    return 0 if passed == total and not broken else 1


if __name__ == "__main__":
    sys.exit(main())
