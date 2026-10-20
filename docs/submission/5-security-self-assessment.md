# 5. Security self-assessment

TR8DE | WeBank FinTechathon 2026 | International Track, Topic F

This assessment covers the deployed Sepolia contracts, the Python agent, the owner console and supplier channels. TR8DE is a testnet prototype using tPHP, a token with no redemption value. It has not had a production security audit and should not hold real funds. The longer finding history, including attacks that worked against earlier revisions, remains in [SECURITY.md](../../SECURITY.md).

The main security claim is narrow: a model can propose a payment, but it cannot sign one. The agent's key signs only after code checks the owner's intent, the policy and the current chain state. The wallet contract then applies its own limits. That design held in the current local regression suite. It is not proof that every live supplier-channel attack is blocked. Two such attacks created PHP 1.00 deals on Sepolia before a fix, and that exact path has not yet had a post-fix live settlement retest.

## 5.1 Who can authorize what

The owner and agent use different keys. The owner key can change limits, save payees, pause the wallet, approve a large deal and attest delivery. The agent key can create escrow, release a deposit, release an attested balance and refund an overdue deal. The model has neither key and sees only draft and read tools. The Python decision is made in [policy.py](../../agent/tiwala_agent/policy.py); the on-chain backstop is [TiwalaAgentWallet.sol](../../src/TiwalaAgentWallet.sol).

| Level | What happens | Boundary |
| --- | --- | --- |
| 0 Read | The agent may inspect balances, deals, reputation and forecasts. | No state-changing call. |
| 1 Autonomous | A complete owner instruction inside the contract threshold can create escrow and pay its deposit. The monitor may refund an overdue deal or release a balance after owner attestation. An unflagged agreed negotiation can settle inside the same limits. | Intent, Checker, policy, single-use Gate, simulation, agent signature and contract rules must all pass. |
| 2 Owner confirmation | A card shows the exact draft when terms were filled by the model, risk was flagged, or the deal is outside the agent's autonomous envelope. | Only the next owner response or the button carrying that card's id can approve it. The action expires after ten minutes and is rechecked against fresh chain state. |
| 3 Refuse | Unknown or blocked payee, mismatched intent, rejected Checker, breached hard cap, inadequate funds or action sourced from contract text. | No Gate authorization is issued. A yes cannot override refusal. |
| Owner key only | Limits, payees, pause, approval above the on-chain threshold, delivery attestation, dispute and withdrawal. | Typed commands bypass the model; the contract checks `onlyOwner`. |

A Tier 2 yes is a chat confirmation, not an owner-key signature. The agent still signs the transaction. If a deal exceeds the contract's `approvalThreshold`, its deposit separately needs an owner-signed `/approve`. A yes cannot bypass the daily payout cap either: the agent waits for the next UTC day or the owner changes the limit with an owner-signed command.

Actions may start from the owner's chat, an agreed negotiation, or the monitor. The monitor may only refund overdue deals and release balances already attested by the owner. Supplier messages and on-chain PO notes are data, not a fourth authority source. Tests include `test_policy_monitor_cannot_create_or_release_down`, `test_the_agent_cannot_raise_its_own_authority`, `test_read_question_must_not_create_model_invented_deal` and `test_owner_stated_in_budget_deal_still_runs_on_its_own`.

## 5.2 Attack paths and controls

### Induced transfers

An attacker can try to substitute a payee, inflate an amount, claim that delivery happened or ask the owner to treat a real payment as a simulation. The payee must come from the owner's own message. Saving a new one requires a valid address, lookalike and blocklist checks, the last four address characters typed back by the owner, an owner-key transaction and the contract's waiting period. The intent verifier binds supplier, amount, deposit percentage and PO to the owner's words. The contract refuses a balance release until the owner key attests delivery.

These are exercised by `test_rt_payout_redirection`, `test_rt_amount_tampering`, `test_rt_fake_delivery_then_real_attestation`, `test_pentest_simulation_wording_never_pays` and the duplicate-create regressions. A forced agent-key balance release [reverted on Sepolia](https://sepolia.etherscan.io/tx/0x0479cd2d2ea18c2403a90278ef526e0adb5b04bf2365f3cb3088606a4e5168d0). The contract still has the release-time payee gap described as R4 below.

### Data extraction

No model tool can read the keys, environment file or Gate secret. Before model calls, [privacy.py](../../agent/tiwala_agent/privacy.py) masks phones, e-mail addresses and account numbers and replaces wallet addresses with placeholders. Supplier-facing APIs do not return the buyer's budget or reserve. A negotiated offer can nevertheless reveal how much the buyer is willing to pay, and local negotiation JSON still stores raw supplier text. Those are R15 and R17, not closed findings. Relevant tests are `test_rt_secrets_cannot_be_extracted`, `test_rt_offchain_data_minimized` and `test_private_limits_stay_on_their_own_side`.

### Privilege escalation

The agent has no tool to run `/limits`, `/approve`, `/attest` or `/freeze`. Owner commands are parsed outside the model and signed with the owner key; the contract rejects those calls from the agent key. The local console uses a login and same-origin write checks. Its WhatsApp tunnel exposes the signed webhook only. Tests cover owner-only contract calls, unauthenticated UI access, forged webhook requests and two concurrent requests racing one confirmation.

### Prompt injection

Owner chat, supplier messages and PO notes can contain instructions that claim higher authority. The input guard tags those patterns, the model sees untrusted text as quoted data, and an action traced to contract text is refused. Flagged supplier threads cannot self-settle after the fourth-assessment fix; an explicit escrow request produces a card for the owner. The regressions are in `test_audit_live.py`, `test_integration.py` and `test_negotiation.py`. A [planted on-chain note](https://sepolia.etherscan.io/tx/0x06a326cfda226cca1dce0369e1118e9f1eaecfa831db75d6fa1b52926dacf205) and its [live transcript](../../reports/live/beat4ac-inject-and-release.txt) show the chain-note boundary. These tests do not establish a measured success rate for live supplier chat after the fix.

## 5.3 What we tested

| Evidence | Result and scope |
| --- | --- |
| Local agent suite | 249/249 passed on 20 October 2026. Chain-backed tests use real contracts on anvil and scripted model outputs. |
| [Scenario report](../../reports/evidence/SUMMARY.md) | 228/228 selected scenarios passed on source commit `217fa48`; 21 provider-adapter tests were excluded. Policy fuzzing checked 200,000 seeded cases with no observed rule violation and caught three planted bugs. |
| Contract tests | Foundry passed 39 unit and fuzz tests plus one invariant suite with three invariants. The baseline invariant handler does not model token-issuer burns. |
| External exercises | An earlier 90-run Promptfoo, PyRIT and Augustus assessment found 13 prohibited payments. Later audits reproduced seven and six more failures. The fixed cases remain in regression tests; the [full history](../../SECURITY.md) distinguishes pre-fix failures from post-fix results. |
| Static and UI checks | Slither reported zero high and zero medium findings, with 14 informational items [triaged](../../reports/slither-triage.md). The 58 UI state checks passed locally. [CI run 34](https://github.com/shaan8/TR8DE/actions/runs/39398585275) passed contracts, agent scenarios, UI build and secret scan; CI does not run Playwright. |

The fourth assessment matters most for interpreting the security result. Its pre-fix supplier-message attacks produced Sepolia deals 7 and 8 and paid PHP 1.00 deposits with the agent key. The current code routes flagged supplier input to owner confirmation, and local regressions pass. Those historical transactions remain evidence of a failure, not a success. The same supplier-channel settlement path has not yet been retested live after the fix.

### The 300-prompt Sepolia campaign

The [campaign bundle](../../reports/evidence/prompt-injection-sepolia-2026-10-20/README.md) records 50 owner-facing prompts in each of six families: instruction override, payment redirection, privilege escalation, secret extraction, embedded untrusted text and confirmation forgery. Qwen `qwen3.7-plus` served the Coordinator and Treasury roles; `qwen3.8-flash` served the Checker. The 300 prompts made 357 model calls: 289 ended in clarification or no action, ten in refusal and one in a confirmation card. There were no model errors and no calls to the transaction sender.

The run read public Sepolia state pinned at block 11,952,943 and allowed `eth_call` simulation. It deliberately disabled transaction broadcasts and omitted the signer during the prompts. Afterwards, the agent wallet sent six zero-value self-transactions, each committing one family's Merkle root. Every prompt/result record has a proof to one of those six transaction hashes. The hashes prove the recorded bundle was committed on Sepolia; they are not 300 payment attempts and they do not prove that the broadcast path would have blocked those prompts.

The campaign used generic suppliers, empty synthetic plans and no prior local conversation. It tested the owner-facing path, not WhatsApp, Telegram or the supplier API. The fourth-assessment supplier attacks are therefore not covered by its zero-broadcast result.

## 5.4 Known risks

The list below separates what the contract enforces from checks that depend on the agent process. Likelihood and impact are judgments for this testnet deployment, not measured probabilities.

- **R1 Agent key compromise — low likelihood, medium impact.** A stolen agent key can create deals and pay deposits to saved suppliers within the contract's per-deal, daily and deposit caps. The owner can pause and rotate the key. Aggregate unapproved commitments still need a tighter cap.
- **R2 Both keys on one demo machine — medium likelihood, high impact.** A host compromise could expose owner authority as well as agent authority. Production needs a separate owner device or hardware wallet.
- **R3 False delivery attestation — medium likelihood, medium impact.** The contract trusts the owner's physical-delivery decision. Disputes stop release, but an oracle or receipt process would be needed for independent proof.
- **R4 Release-time payee checks — low likelihood, medium impact.** Python rechecks cooling, removal and blocklists. A stolen agent key can bypass Python. The deployed deposit function checks only that the supplier is listed; the balance path lacks equivalent payee checks. This needs a contract fix and redeployment.
- **R5 Colluding buyers manufacture reputation — low likelihood, medium impact.** The platform gates wallet creation and account hashes cannot be reused, but the score itself credits onboarded buyers. Verified-buyer value and age floors would help.
- **R6 Seeded reputation — demonstration limitation.** The suppliers' starting history is synthetic and labelled. It is not independent commercial trade history.
- **R7 Old events have equal weight — medium likelihood, low impact.** Reputation has no recency decay. Age weighting remains future work.
- **R8 Optimistic receivables — medium likelihood, low impact.** The cash forecast uses the owner's planned inflows without a haircut. The contract still refuses an unfunded escrow.
- **R9 Model-provider exposure — high likelihood, low impact under current masking.** Names, amounts and dates reach the provider, although direct identifiers and wallet addresses are masked. Sensitive buyers would need a self-hosted model.
- **R10 Free-text counter misinterpretation — medium likelihood, low impact.** A model can misread a counteroffer, but free text never counts as acceptance; the canonical terms are echoed and an exact code is required.
- **R11 Global login lockout — low likelihood, low impact.** Anyone able to reach the login page could lock out the owner for 15 minutes. The documented deployment binds the console locally and exposes only the webhook.
- **R12 Telegram invite link — low likelihood, low impact.** It is a bearer link until first use, though hashed, single-use and seven-day limited. The supplier is told when the chat is linked.
- **R13 Evidence provenance — closed reproducibility issue.** [SUMMARY.md](../../reports/evidence/SUMMARY.md) now pins the source commit used for the scenario run; it is separate from the commit that added the report.
- **R14 Test token and immutable contracts — deployment limitation.** tPHP has no redemption value. Fixing a contract gap requires a new deployment.
- **R15 Negotiation can reveal a private ceiling — observed, medium commercial impact.** Private limit fields stay out of supplier views, but a visible counteroffer can equal the buyer's maximum. A concession rule can reduce inference; injection causality was not established.
- **R16 Underfunded deposit — low likelihood, medium impact.** A privileged token issuer can burn escrow balance and a compromised agent can then invoke `releaseDownPayment`; the contract lacks an `isUnderfunded` guard there. Python blocks that state, but the contract requires redeployment. The baseline invariants do not model issuer burns.
- **R17 Supplier text retained locally — expected exposure, low impact.** Negotiation JSON stores raw supplier messages and old audit logs are not rewritten. Retention limits, sanitisation and restricted storage permissions remain needed.
- **R18 Counter prose and structured offer — observed, medium consent risk.** The buyer model once wrote text that contradicted its offer. Supplier-facing prose now comes from validated terms, while the model may still choose an undesirable offer within the buyer's limits.
- **R19 Delivery-date intent — unquantified, medium impact.** The deterministic intent parser does not bind the owner's date wording. The Checker reviews dates and code requires a future deadline, but autonomous deals need deterministic date binding or an explicit review when date wording is unresolved.

## 5.5 Assessment boundary

The Checker uses a different Qwen variant from the Coordinator, but both can share provider or reasoning errors. The contract protects roles, caps and deal states even if Python is bypassed, subject to R4 and R16. Intent matching, blocklists, duplicate prevention and most prompt-injection controls remain off-chain.

Before real funds, the contract release gaps need a new deployment, owner signing needs separation from the agent host, supplier text needs a retention policy, and the fixed supplier-message path needs a live retest. For this competition, the next useful proof is the planned live demo transaction: record the owner input, decision, signer, transaction hash and resulting contract state together. Keep that in execution evidence, which is being held for the actual demo.
