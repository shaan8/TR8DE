# Security self-assessment

Scope: `src/` contracts, the Python agent in `agent/tiwala_agent/`, and the Sepolia demo deployment.
Status: hackathon prototype on testnet with a test token (tPHP). Not audited. Do not use with real funds.

## Threat model

| Asset | Who could attack it | Main defence |
| --- | --- | --- |
| Escrowed funds | Compromised or misled agent key | Contract limits the agent key (below); owner-only actions need the owner key |
| Owner intent | Prompt injection via PO notes, supplier names, chat | Input guard wraps chain text as data; intent verifier compares actions to the owner's own words |
| Payee list | Injected, poisoned or mistyped payout addresses | Payee checks in code (`payee.py`): the address must be in the owner's own words, EIP-55 checksum, no lookalike of a saved address or name, no wallet roles or blocklist; owner types its last 4 characters; owner key signs `addSupplier`; contract waits `supplierDelay` |
| Supplier reputation | Fake buyers inflating a supplier's record | Platform-gated factory with account-hash dedup; buyer-history weighting; causal median (non-delivery never raises R) |
| Audit trail | Tampering after the fact | Hash-chained JSONL; `/verify` recomputes the chain |

## Layered controls

The design assumes any LLM can be fooled. Each layer below holds even if every layer above it fails.

1. **LLM agents (advisory only).** The Coordinator drafts; the Checker, on a different model, reviews and fails
   closed on errors or unparseable output. Neither can sign.
2. **Deterministic gate (`core.py`, `policy.py`, `intent.py`, `guard.py`).** Every action needs an HMAC Gate
   authorization minted only after the policy engine allows it. Tier 2 actions need a confirmation matched on the
   owner's own next message, not on model output. Owner-tier actions run only from typed slash commands. A new payee is saved only after the
   payee checks pass and the owner types the address's last 4 characters; the owner key signs it.
3. **Scoped signer (`chain.py`).** The agent key can call only operator functions; each call is simulated first.
4. **Contract (`TiwalaAgentWallet`).** For the agent key:
   - payees must be whitelisted by the owner and active after `supplierDelay`
   - `perDealCap`, `dailyCap` (UTC day), `maxDownBps` and `approvalThreshold` bound every deal
   - `releaseBalance` requires owner attestation (`confirmDelivery`); refunds before the deadline plus grace revert
   - `withdraw`, `setAgent`, `setLimits`, disputes and resolutions are owner-only
   - `pause` stops agent payouts; `SafeERC20` and `nonReentrant` on every transfer path

## Evidence

| Check | Result |
| --- | --- |
| Foundry: 38 unit, 1 fuzz, 3 invariants (conservation, locked equals open deals, pre-attestation payout bounded) | 42 pass, 256 runs x 64 depth, 0 reverts ([`reports/tests.txt`](reports/tests.txt)) |
| Agent: deterministic layer + red-team on anvil | 74 pass |
| Slither 0.11.6 on `src/` | 0 high, 0 medium; 14 informational, triaged in [`reports/slither-triage.md`](reports/slither-triage.md) |
| Live red-team on Sepolia | Injection, unknown payee, forced revert, social engineering: all held ([`README.md`](README.md#live-agent-run-on-sepolia)) |

## Known limitations

- **Agent key compromise.** An attacker holding the agent key can still create deals and release down payments to
  already-whitelisted suppliers, up to `perDealCap`, `dailyCap` and `maxDownBps`. Loss is bounded, not zero.
  The owner can `pause` and `setAgent` to rotate.
- **Owner key on the same device in the demo.** The CLI holds both keys for the demo. Production should keep the
  owner key on a separate device or hardware wallet so a compromised agent host cannot attest.
- **Owner attestation is trusted.** The contract cannot verify physical delivery; a careless `/attest` releases funds.
  Disputes stop a release but rely on off-chain resolution.
- **Reputation is off-chain and computed by the agent.** A bug in `reputation.py` could set a wrong cap; the
  contract's `maxDownBps` is the hard ceiling. Sybil resistance depends on the platform's account dedup.
- **LLM provider sees conversation content.** The audit log is redacted; prompts sent to the provider are not.
- **Timestamps.** Deadlines use `block.timestamp`; drift of seconds does not matter at hour and day granularity.
- **Single chain, test token, no upgrade path.** Contracts are not upgradeable; a fix means a new deployment.
- **Novelty and prior art** have not been formally checked.
