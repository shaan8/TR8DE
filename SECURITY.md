# Security self-assessment

Scope: `src/` contracts, the Python agent in `agent/tiwala_agent/` (including account connectors), and the Sepolia demo deployment.
Status: hackathon prototype on testnet with a test token (tPHP). Not audited. Do not use with real funds.

## Threat model

| Asset | Who could attack it | Main defence |
| --- | --- | --- |
| Escrowed funds | Compromised or misled agent key | Contract limits the agent key (below); owner-only actions need the owner key |
| Owner intent | Prompt injection via PO notes, supplier names, chat | Input guard wraps chain text as data; intent verifier compares actions to the owner's own words |
| Supplier reputation | Fake buyers inflating a supplier's record | Platform-gated factory with account-hash dedup; buyer-history weighting; causal median (non-delivery never raises R) |
| Audit trail | Tampering after the fact | Hash-chained JSONL; `/verify` recomputes the chain |
| Linked-account credentials | Theft from disk, leakage to the LLM or logs, over-broad keys | Fernet vault (0600), secrets never leave `connectors.py`, read-only scope checks on link |
| Forecast inputs | Owner or attacker inflating balances to hide a shortfall | No manual entry; amounts only from provider APIs over pinned HTTPS, never stored on disk |

## Layered controls

The design assumes any LLM can be fooled. Each layer below holds even if every layer above it fails.

1. **LLM agents (advisory only).** The Coordinator drafts; the Checker, on a different model, reviews and fails
   closed on errors or unparseable output. Neither can sign.
2. **Deterministic gate (`core.py`, `policy.py`, `intent.py`, `guard.py`).** Every action needs an HMAC Gate
   authorization minted only after the policy engine allows it. Tier 2 actions need a confirmation matched on the
   owner's own next message, not on model output. Owner-tier actions run only from typed slash commands.
3. **Scoped signer (`chain.py`).** The agent key can call only operator functions; each call is simulated first.
4. **Contract (`TiwalaAgentWallet`).** For the agent key:
   - payees must be whitelisted by the owner and active after `supplierDelay`
   - `perDealCap`, `dailyCap` (UTC day), `maxDownBps` and `approvalThreshold` bound every deal
   - `releaseBalance` requires owner attestation (`confirmDelivery`); refunds before the deadline plus grace revert
   - `withdraw`, `setAgent`, `setLimits`, disputes and resolutions are owner-only
   - `pause` stops agent payouts; `SafeERC20` and `nonReentrant` on every transfer path

## Account connectors (`connectors.py`)

Off-chain balances are inputs to the forecast only. They can never unlock or move escrow.

- **Read-only by construction.** Each adapter calls a single balance endpoint. Stripe accepts only restricted keys
  and probes that the key cannot read charges. PayPal links need the reporting read scope. Plaid tokens carry no
  money-movement product.
- **Pinned egress.** HTTPS only, to an allowlist of provider hosts, no redirects, 10 s timeout. Lookalike hosts and
  metadata IPs are blocked.
- **Secrets.** Fernet-encrypted at rest (`TIWALA_VAULT_KEY`, else a 0600 key file). They are never returned to
  callers, never logged, never placed in a prompt. Unlinking deletes them and revokes the Plaid item.
- **Data minimization (RA 10173).** Parsers keep provider, amount, currency and time. Account numbers, masks,
  names and payer IDs are dropped. Every link needs an explicit consent record.
- **Provider-only amounts.** There is no manual entry and no amount field anywhere. Balances are fetched live,
  held in memory for 2 minutes and never written to disk. `links.json` holds metadata only: a hand-written or
  edited record yields nothing without a valid provider token. Provider hosts and FX rates are fixed in code.
  Balances older than 24 hours are left out.
- **Fail safe.** A revoked token, provider error or unknown currency contributes nothing to the forecast and shows
  an error in the UI, without echoing the provider response.

## Evidence

| Check | Result |
| --- | --- |
| Foundry: 38 unit, 1 fuzz, 3 invariants (conservation, locked equals open deals, pre-attestation payout bounded) | 42 pass, 256 runs x 64 depth, 0 reverts ([`reports/tests.txt`](reports/tests.txt)) |
| Agent: deterministic layer + red-team on anvil | 74 pass |
| Connectors: scope checks, pinned egress, field allowlist, secret leakage, revocation, staleness, consent, tamper attempts on stored links | 28 pass (recorded provider responses, no network) |
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
- **PayPal app credentials are broader than read.** Without PayPal partner approval, a merchant's own REST app is
  the only way to read its balance, and those credentials can also create payments. Tiwala calls only the balances
  endpoint and warns on link; production would use partner consent scoped to read.
- **Vault key on the same host in the demo.** With no `TIWALA_VAULT_KEY`, the key file sits beside the vault.
  Production keeps it in an OS keychain or KMS.
- **Indicative FX.** Non-PHP balances use rates fixed in code; a stale rate skews the forecast, never a payment.
- **Host compromise.** Someone who controls the machine running the agent can alter its code. Provider-only
  amounts stop editing through the app or its files, not a rooted host.
- **Live provider paths are tested against recorded responses.** Sandbox runs need the owner's own keys.
- **Novelty and prior art** have not been formally checked.
