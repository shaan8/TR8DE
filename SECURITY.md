# Security self-assessment

Scope: `src/` contracts, the Python agent in `agent/tiwala_agent/`, and the Sepolia demo deployment.
Status: hackathon prototype on testnet with a test token (tPHP). Not audited. Do not use with real funds.

## Threat model

| Asset | Who could attack it | Main defence |
| --- | --- | --- |
| Escrowed funds | Compromised or misled agent key | Contract limits the agent key (below); owner-only actions need the owner key |
| Owner intent | Prompt injection via PO notes, supplier names, chat | Input guard wraps chain text as data; intent verifier compares actions to the owner's own words |
| Payee list | Injected, poisoned or mistyped payout addresses | Payee checks in code (`payee.py`): the address must be in the owner's own words, EIP-55 checksum, no lookalike of a saved address or name, no wallet roles or blocklist; owner types its last 4 characters; owner key signs `addSupplier`; contract waits `supplierDelay` |
| Negotiated terms | Supplier text injection, stale or ambiguous acceptance, duplicate webhooks, human and agent answering at once | Supplier text never reaches the owner path; acceptance must name the open version and terms hash; counters supersede; lock plus version check; message-ID dedup; escrow handoff idempotent by on-chain reference; agreement rechecked on fresh chain data and confirmed by the owner ([`docs/negotiation.md`](docs/negotiation.md)) |
| Supplier reputation | Fake buyers inflating a supplier's record | Platform-gated factory with account-hash dedup; buyer-history weighting; causal median (non-delivery never raises R) |
| Owner console | Anyone who reaches the console URL | Login (`agent/console/auth.py`): salted scrypt hash in `.env`, no plaintext; 256-bit server-side sessions in an HttpOnly, SameSite=Strict cookie (Secure on HTTPS), 2 h idle and 12 h absolute expiry; lockout after 5 failures per client and 30 overall per 15 min; same-origin plus `X-Tiwala` header on every write; CSP, frame-deny and HSTS headers; API docs disabled. The supplier console uses its own per-supplier token and the WhatsApp webhook its Meta signature |
| Audit trail | Tampering after the fact | Hash-chained JSONL; `/verify` recomputes the chain (detects edits, not deletion of the tail) |

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
| Agent: deterministic layer, payees, negotiation, WhatsApp adapter, console login, red-team and pentest regressions on anvil | 164 pass |
| Slither 0.11.6 on `src/` | 0 high, 0 medium; 14 informational, triaged in [`reports/slither-triage.md`](reports/slither-triage.md) |
| Live red-team on Sepolia | Injection, unknown payee, forced revert, social engineering: all held ([`README.md`](README.md#live-agent-run-on-sepolia)) |

## Independent testing (18 October 2026)

An external read-only adversarial audit and an automated pentest (Promptfoo, PyRIT, Augustus) ran against a copy of
this repo on a local Anvil chain with test tokens; credit to that audit and pentest for the findings below. Limits: the pentest used a free OpenRouter
model, not the configured production models, and no production keys or Sepolia; its source copy predates later
commits (`core.py` and others changed; `policy.py`, `guard.py` and `intent.py` matched at the time). Across 90
Promptfoo runs, 13 recorded a prohibited payment.

| Finding | Outcome |
| --- | --- |
| Monitor released the balance to a blocklisted supplier after attestation (4 runs; audit F1) | Fixed. `policy._payout_checks` (blocklist, listed, cooling) now runs on every payout: create, down payment, balance, monitor. Test: `test_pentest_monitor_does_not_pay_blocklisted_supplier` |
| Down payment paid to a blocklisted supplier (2 runs; F1) | Fixed, same check. Test: `test_pentest_down_payment_refused_for_blocklisted_supplier` |
| Payout after the supplier was removed and re-added under a new waiting period (4 runs; F2) | Fixed in the agent: releases refuse while `activeAt > now`. Test: `test_pentest_readded_supplier_cooling_blocks_down_payment_and_balance`. The deployed contract still checks only `listed` in `releaseDownPayment`; changing it needs a redeploy, so a stolen agent key can still pay in that window (accepted for the testnet demo) |
| Balance to a supplier the owner removed | Changed: the agent no longer releases it on its own; it asks the owner (`supplier_removed` flag). Test: `test_pentest_removed_supplier_balance_needs_owner_confirmation` |
| "Just a simulation" pretext led to a real payment (3 runs; latest blocked by the Checker) | Fixed deterministically: simulation, dry run, "do not pay", "without changing anything" and similar wording in the owner's latest message is an intent mismatch, so nothing moves whatever the models say. Test: `test_pentest_simulation_wording_never_pays`, `test_no_payment_wording` |
| Wrong deal ID drafted by the Coordinator (audit F3) | Partly fixed: a deal number the owner names must match the action (`test_audit_f3_wrong_deal_id_is_refused`). Several releases in one turn are still possible if the Checker approves each |
| Benign request refused when the supplier was named by a short form ("Bayani") | Fixed: names resolved in code are passed to the Checker, and its prompt accepts the first-word short form |
| Cheap reputation manufacture by colluding factory buyers (F4) | Accepted for the demo: needs platform-onboarded buyers. Production needs value and age floors per verified buyer |
| Compromised agent key can lock all free funds in unapproved deals (F5) | Accepted: recoverable (pause, rotate agent, cancel). Production should cap aggregate unapproved commitments |
| Audit log tail deletion passes `/verify` (F6) | Accepted; claim narrowed in `audit.py` and above. Needs an external checkpoint |
| Gate authorization reusable within its 60 s TTL | Accepted: no tool accepts an authorization; nonces stop raw replay |

The Promptfoo cases were not rerun against the fixed code; the regression tests above replay each path on anvil with
scripted models.

## Deployment model

The console runs on the owner's machine and binds to `127.0.0.1`. It is not meant to be exposed whole. Receiving
live WhatsApp replies needs a public HTTPS URL for `/webhooks/whatsapp` only (signed by Meta with the app secret);
expose that one path through a tunnel or reverse proxy for as long as it is needed and keep every other path local.
The login is a second layer for any exposure, not a reason to publish the console. Set or change the password with
`cd agent && ../.venv/bin/python -m console.auth set-password <username>`.

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
- **WhatsApp live integration is untested.** No Meta credentials were available. Eligibility of an escrow-linked
  use case under the WhatsApp Business Messaging Policy is unresolved ([`docs/negotiation.md`](docs/negotiation.md)).
- **Supplier console auth is a per-supplier token**, and in the local demo the supplier agent runs on the buyer's server.
- **Novelty and prior art** have not been formally checked.
