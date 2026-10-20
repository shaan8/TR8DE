# TR8DE: submission map

WeBank FinTechathon 2026, International Track, Topic F. Submission documents and supporting [README](README.md) sections:

| Deliverable | Where |
| --- | --- |
| Technical documentation | [Deliverable 1](docs/submission/1-technical-documentation.md), [1. Technical documentation](README.md#1-technical-documentation), [negotiation design](docs/negotiation.md) |
| Source code, deployment, tests | [2. Source code](README.md#2-source-code), [0. How to deploy](README.md#0-how-to-deploy) |
| Security self-assessment | [Deliverable 5](docs/submission/5-security-self-assessment.md), [3. Security self-assessment](README.md#3-security-self-assessment), full report in [SECURITY.md](SECURITY.md) |
| Execution evidence | [Deliverable 6](docs/submission/6-execution-evidence.md), [4. Execution evidence](README.md#4-execution-evidence), every transaction in [reports/sepolia-evidence.md](reports/sepolia-evidence.md) |
| Presentation deck | Submitted with the entry form |
| Demo video | Recording pending; [5-minute plan](docs/submission/demo-plan.md) |

## How the scoring areas are covered

| Area | Evidence |
| --- | --- |
| Task completion | Live Sepolia runs: deal creation, deposit, attestation, balance release, overdue refund, payee saving, negotiation to escrow. Scenario group A in [reports/evidence/SUMMARY.md](reports/evidence/SUMMARY.md) |
| Safe execution and owner control | The agent acts alone only inside the `approvalThreshold` the owner sets on the contract, and only on terms the owner stated. Anything else needs the owner's yes on that exact card. Caps, daily limit, payee waiting period, circuit breaker, `/freeze`. Group B |
| Attack resistance | Prompt injection (chat, contract text, supplier messages), payout redirection, amount tampering, simulation pretexts, stale cards, duplicate creates, login attacks. Group C, 200k-case policy fuzz, four external assessments in [SECURITY.md](SECURITY.md) |
| Privacy and integrity | Data minimised before model calls; private constraint fields stay buyer-side, though offers can reveal the ceiling; hash-chained audit log anchored on Sepolia ([verify_audit.py](scripts/verify_audit.py)). Group D |

Status: hackathon prototype on a testnet with a test token. Not audited for production; do not use with real funds.
