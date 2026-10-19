# Tiwala: submission map

WeBank FinTechathon 2026, International Track, Topic F. Tiwala is an escrow payment agent for small businesses:
it negotiates supplier terms, locks the exact agreement in an on-chain escrow on Sepolia, and pays only within
limits the contract enforces and the owner approves.

| Deliverable | Where |
| --- | --- |
| Technical documentation: architecture, core algorithms, security design | [`README.md`](README.md) (layout, agent core, run and deploy), [`docs/negotiation.md`](docs/negotiation.md) (negotiation engine, WhatsApp), [`SECURITY.md`](SECURITY.md) (security design) |
| Presentation deck | `docs/deck.pdf` (to be added: exported from the team's deck before submission) |
| Source code | `src/` (Solidity contracts), `agent/` (Python agent and console API), `ui/` (React console) |
| Deployment instructions | One-command local demo: [`scripts/local-demo.sh`](scripts/local-demo.sh) ([README](README.md#try-it-on-your-machine-one-command)); Sepolia: [`README.md`](README.md#deploy-to-sepolia), [`scripts/deploy-sepolia.sh`](scripts/deploy-sepolia.sh) |
| Integration for suppliers' own agents | [`docs/supplier-api.md`](docs/supplier-api.md), example agent [`scripts/supplier_agent_example.py`](scripts/supplier_agent_example.py) |
| Test cases | `test/` (Foundry: unit, fuzz, invariants), `agent/tests/` (agent, red team, pentest regressions, policy fuzz, login), `ui/tests/` (UI states, Playwright); contract and agent tests plus the UI build run in [CI](.github/workflows/ci.yml) |
| Security self-assessment | [`SECURITY.md`](SECURITY.md): threat model, layered controls, independent testing and outcomes, deployment model, known limitations |
| Execution evidence (on-chain) | [`reports/sepolia-evidence.md`](reports/sepolia-evidence.md): contracts and every transaction on Sepolia; [`reports/live/`](reports/live) agent transcripts and hash-chained audit log from the live runs |
| Execution evidence (scenarios) | [`reports/evidence/SUMMARY.md`](reports/evidence/SUMMARY.md): every scenario grouped as task completion, safe execution, attacks blocked, privacy and integrity; policy fuzz statistics. Reproduce with `scripts/evidence.py` |
| Demo video | See [`docs/demo-runbook.md`](docs/demo-runbook.md) for the recorded beats |

## How the scoring areas are covered

| Area | Evidence |
| --- | --- |
| Task completion | Live Sepolia runs (deal creation, deposit, attestation, balance release, overdue refund, payee saving, negotiation to escrow); scenario group A |
| Safe execution and owner control | Every new deal and payee needs the owner's own confirmation; contract caps, daily limit and supplier waiting period; circuit breaker and `/freeze`; scenario group B |
| Attack resistance | Prompt injection (direct, contract text, supplier messages), payout redirection, amount tampering, privilege claims, simulation pretexts, blocklisted and re-added suppliers, cross-site and brute-force login attempts; scenario group C, 200k-case policy fuzz, external pentest outcomes in `SECURITY.md` |
| Privacy and integrity | Data minimised before model calls; private negotiation limits never leave the buyer side; hash-chained audit log anchored on Sepolia and verifiable offline with [`scripts/verify_audit.py`](scripts/verify_audit.py); scenario group D |

## Verify it yourself

```bash
python3 scripts/verify_audit.py reports/live/audit.jsonl          # audit chain from the live Sepolia runs
PATH=$HOME/.foundry/bin:$PATH .venv/bin/python scripts/evidence.py  # all scenarios on a local chain
```

Status: hackathon prototype on a testnet with a test token. Not audited for production; do not use with real funds.
