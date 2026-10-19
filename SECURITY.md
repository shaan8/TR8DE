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
| Supplier API | Another supplier, a leaked token, stale or replayed moves | Per-supplier Bearer token scoped to that supplier's own negotiations; moves must name the open version and terms hash; the buyer's limits are never returned |
| Supplier chat (WhatsApp, Telegram) | A stranger messaging the bot, a flood from a bound chat, a forged webhook | Only bound, opted-in senders reach the engine; WhatsApp posts need Meta's HMAC signature; Telegram is pulled by long polling and binds a chat only through a one-time, hashed, expiring invite; 20 messages per 10 minutes per sender; STOP opts out |
| Owner console | Anyone who reaches the console URL | Login (`agent/console/auth.py`): salted scrypt hash in `.env`, no plaintext; 256-bit server-side sessions in an HttpOnly, SameSite=Strict cookie (Secure on HTTPS), 2 h idle and 12 h absolute expiry; lockout after 5 failures per client and 30 overall per 15 min; same-origin plus `X-Tiwala` header on every write; CSP, frame-deny and HSTS headers; API docs disabled. The supplier console uses its own per-supplier token and the WhatsApp webhook its Meta signature |
| Audit trail | Tampering after the fact | Hash-chained JSONL; `/anchor` writes the head hash and entry count to Sepolia from the owner key, so edits, deletions and tail truncation up to the last anchor are detected by [`scripts/verify_audit.py`](scripts/verify_audit.py) (standard library only, works offline) |

## Layered controls

The design assumes any LLM can be fooled. Each layer below holds even if every layer above it fails.

1. **LLM agents (advisory only).** The Coordinator drafts; the Checker, on a different model, reviews and fails
   closed on errors or unparseable output. Neither can sign.
2. **Deterministic gate (`core.py`, `policy.py`, `intent.py`, `guard.py`).** Every action needs an HMAC Gate
   authorization minted only after the policy engine allows it. Tier 2 actions need a confirmation matched on the
   owner's own next message, not on model output. The line between Tier 1 and Tier 2 for a new deal is the
   contract's own `approvalThreshold`: inside it the agent creates the deal and releases the deposit itself, and
   above it the owner confirms. The policy never reaches past that line, and it tightens on its own terms, asking
   the owner whenever a deal is flagged, the payee is not yet active, today's limit would be exceeded or the
   Checker declines. `agent_authority()` in `policy.py` is the single place that decides this. The owner moves that line with the
   typed `/limits` command, signed with the owner key; there is no tool for it, so no model and no injected
   message can raise the authority the agent holds over the owner's money
   (`test_the_agent_cannot_raise_its_own_authority`). `/limits` deliberately leaves the payee waiting period
   alone, since lowering it is what an attacker would want. Owner-tier actions run only from typed slash commands. A new payee is saved only after the
   payee checks pass and the owner types the address's last 4 characters; the owner key signs it.
   Each Gate authorization is single-use. Model replies are grounded: a transaction hash not produced here
   replaces the reply, and peso amounts not taken from wallet data are flagged. Three refused payment requests
   within 10 minutes freeze the agent (circuit breaker); `/freeze` also pauses the wallet on-chain.
   Every payout path (create, down payment, balance, monitor) re-runs the blocklist and supplier status checks.
3. **Scoped signer (`chain.py`).** The agent key can call only operator functions; each call is simulated first.
4. **Contract (`TiwalaAgentWallet`).** For the agent key:
   - payees must be whitelisted by the owner and active after `supplierDelay`: a newly saved payee cannot be paid
     until it passes, so a payee added through phishing, injection or a stolen session can be removed before any
     money moves. Production setting 24 hours; the run scripts deploy with 10 minutes (`PAYEE_DELAY`) so judges
     can watch the rule work in one session. Our own Sepolia deployment uses 24 hours
   - `perDealCap`, `dailyCap` (UTC day), `maxDownBps` and `approvalThreshold` bound every deal.
     `approvalThreshold` is the owner's autonomy budget: `needsApproval = msg.sender != owner && total >
     approvalThreshold`, so the agent commits funds alone only below it, and the owner sets it with `setLimits`
   - `releaseBalance` requires owner attestation (`confirmDelivery`); refunds before the deadline plus grace revert
   - `withdraw`, `setAgent`, `setLimits`, disputes and resolutions are owner-only
   - `pause` stops agent payouts; `SafeERC20` and `nonReentrant` on every transfer path

## Evidence

| Check | Result |
| --- | --- |
| Foundry: 38 unit, 1 fuzz, 3 invariants (conservation, locked equals open deals, pre-attestation payout bounded) | 42 pass, 256 runs x 64 depth, 0 reverts ([`reports/tests.txt`](reports/tests.txt)) |
| Agent: deterministic layer, payees, negotiation, WhatsApp adapter, console login, red-team and pentest regressions on anvil | All pass; grouped in [`reports/evidence/SUMMARY.md`](reports/evidence/SUMMARY.md), run in [CI](.github/workflows/ci.yml) |
| Policy fuzzing: 200,000 seeded random cases, every payout rule checked after each decision | 0 violations; three planted bugs each caught |
| Secret scan of the full git history (gitleaks in CI, plus a check of every `.env` value) | No secrets committed; only the public Anvil test keys, allowlisted |
| Slither 0.11.6 on `src/` | 0 high, 0 medium; 14 informational, triaged in [`reports/slither-triage.md`](reports/slither-triage.md) |
| Live red-team on Sepolia | Injection, unknown payee, forced revert, social engineering: all held ([`README.md`](README.md#4-execution-evidence)) |

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
| Audit log tail deletion passes `/verify` (F6) | Fixed: on-chain anchors via `/anchor`; `scripts/verify_audit.py` reports deleted or rewritten entries. Entries after the last anchor are covered only once the next anchor is written |
| Gate authorization reusable within its 60 s TTL | Fixed: each authorization carries a nonce and is consumed on use |

The Promptfoo cases were not rerun against the fixed code; the regression tests above replay each path on anvil with
scripted models.

## Second independent audit (20 October 2026)

A second external audit of commit `b4244b8` reproduced seven failures on a local Anvil chain with scripted models
and test tokens. Its tests are kept as `agent/tests/test_audit_regressions.py` and all pass now.

| Finding | Outcome |
| --- | --- |
| The Streamlit UI (`agent/app.py`) had no login and signed owner commands such as `/attest` (high) | Fixed: the page asks for the same owner login as the console before it builds anything or loads the owner key, and refuses to start when no login is set up. Test: `test_streamlit_cannot_sign_owner_commands_without_authentication` |
| Two identical create calls in one request made two escrows and paid both deposits (high) | Fixed: a create is once-only. The same action twice in a turn, or a PO reference that already has an open deal on chain, is refused, also at confirmation time. If the open-deal check cannot read the chain, nothing is created. Test: `test_one_request_cannot_create_the_same_po_twice` |
| After a deal was paid, a model outage replied "Nothing was drafted or sent" (high) | Fixed: the reply lists every transaction already sent this turn. Test: `test_model_failure_after_execution_must_not_say_nothing_was_sent` |
| A receipt timeout after broadcast lost the transaction hash (high) | Fixed: the hash is returned and logged as `tx_pending`, and the reply says to check it before asking again. Test: `test_receipt_timeout_must_leave_a_recoverable_transaction_hash` |
| A negotiated card still executed after the agreement expired, or below the negotiated reserve (high) | Fixed: just before the owner's yes signs, the negotiation re-checks expiry, the agreed terms hash and every hard buyer constraint on chain state read then. Tests: `test_negotiated_expiry_is_rechecked_when_owner_confirms`, `test_negotiated_min_reserve_is_rechecked_when_owner_confirms` |
| Concurrent appends forked the audit hash chain (medium) | Fixed: appends hold a thread lock and an exclusive file lock, and re-read the head hash if another process wrote. Test: `test_audit_log_survives_concurrent_writers` |
| The public WhatsApp tunnel reached the console's webhook with any request; only the console checked Meta's token and signature | Hardened: the gate now checks the verify token and the HMAC signature itself, accepts JSON only, rate-limits to 120 requests a minute, drops slow clients after 10 s and will not start without both secrets. Tests: `test_forged_calls_stop_at_the_gate`, `test_a_flood_is_rate_limited` |
| Off-chain evidence does not pin the agent revision that produced it | Open. Deployed bytecode matches the pinned build; regenerated evidence should record the commit |

## Third independent audit (20 October 2026)

A third external audit of commit `a61a4ff` reproduced six failures on a local Anvil chain with scripted models. Its
probes are kept as `agent/tests/test_audit_focus.py` and all pass now. They show a missing deterministic boundary,
not a measured attack rate against the live models.

| Finding | Outcome |
| --- | --- |
| A question ("What is Lumen's delivery record?") led a scripted model to create and fund an escrow on its own (high) | Fixed: a chat-requested deal runs without a card only when the owner's own words name the supplier, total, down payment % and PO reference. Any term the model filled in sends it to a confirmation card that lists those terms. Test: `test_read_question_must_not_create_model_invented_deal` |
| The Confirm button sent a bare "yes", so it could approve a card that had replaced the one on screen (high) | Fixed: every card has an id, the console and Streamlit buttons send it, and a yes for any other card approves nothing. Test: `test_stale_card_confirmation_must_not_approve_replacement` |
| Declining a negotiated escrow card left the negotiation stuck waiting for it (high) | Fixed: a declined or replaced card hands the agreement back, so it can be sent to escrow again or closed. Test: `test_declining_escrow_must_allow_negotiation_to_close` |
| Two requests before mining created two escrows for one PO (high) | Fixed: a create whose receipt has not come back is recorded on disk with its tx hash, and any further create for that PO waits until it is mined or has been gone for 10 minutes. Test: `test_pending_create_must_not_be_broadcast_again` |
| Hitting the tool-step limit replied "Nothing was paid" after a deposit (high) | Fixed: every exit path lists the transactions this turn sent, read from the audit events. Test: `test_step_limit_must_report_already_sent_payment` |
| The forecast added past receipts to today's balance again (medium) | Fixed: inflows dated before today are already in the on-chain balance and are ignored. The contract still refuses an unfunded escrow. Test: `test_past_inflow_must_not_inflate_current_balance` |

## Judge walkthrough (19 October 2026)

We cloned the public repository into an empty folder, ran `./scripts/local-demo.sh` exactly as the README says
(no keys, no `.env`), signed in with the printed one-time login, and attacked the running console from outside
(curl, concurrent requests, oversized bodies, path tricks), then read every route and entry point in the code.

| # | Finding | Severity | Outcome |
| --- | --- | --- | --- |
| J1 | Chat, the Confirm button, the monitor (`/api/tick`) and the escrow handoff all read and clear the same pending confirmation with no lock. Two requests at the same moment could both act on one owner "yes" and execute it twice (Gate authorizations are single-use, but each request mints its own). Four concurrent confirms against the demo executed once, but only because the window is narrow. | High | Fixed: one re-entrant turn lock around every owner entry point (`Tiwala.handle`, `tick`, `request_escrow`). Test: `test_owner_turns_are_serialized` |
| J2 | No request size limit. Public endpoints (login, WhatsApp webhook, supplier API) read the whole body before any check; a 50 MB login body was accepted for parsing. | Medium | Fixed: 256 KB cap in front of every route, by `Content-Length` and by counting chunked bodies; 413 before parsing. Test: `test_oversized_bodies_are_refused_before_parsing` |
| J3 | The supplier console link carried its token in the query string, so it ended up in browser history and sync, any proxy or access log, and screen recordings. | Medium | Fixed: links use `#token=` (never sent to the server or in `Referer`); the page moves it into `sessionStorage`, removes it from the address bar and sends it as `X-Supplier-Token`. Old `?token=` links still work. Test: `test_supplier_page_token_travels_in_a_header_not_the_url` |
| J4 | A bound WhatsApp or Telegram chat could send unlimited messages, each one a model call (cost and log flooding). | Low | Fixed: 20 messages per 10 minutes per sender reach the engine; the owner is told once. Test: `test_chat_flood_from_a_bound_sender_is_capped` |
| J5 | The local demo blanked WhatsApp settings but not Telegram: a `TELEGRAM_BOT_TOKEN` in `.env` would make the throwaway demo poll and send for real. Its supplier-token secret fell back to `date +%s%N` (predictable, and `%N` is not supported on macOS). | Low | Fixed: the demo blanks every Telegram setting; the secret comes from Python's `secrets` |
| J6 | Python dependencies were version ranges, so a judge's install could differ from the tested one. | Low | Fixed: `agent/requirements.lock` pins the direct dependencies and starlette; checked to resolve on Python 3.11 to 3.14 for macOS, Linux and Windows; the scripts and CI install with it |
| J7 | With no model key, the chat named only `DEEPSEEK_API_KEY`. | Info | Fixed: it names all four providers. Test: `test_offline_message_names_every_provider` |
| J8 | `deploy-sepolia.sh` ran `.env` as shell code (`source .env`), so a double-quoted value containing `$` (a scrypt hash) or a value with spaces aborted the live deployment, and `set-password` could create `.env` readable by other users. | Low | Fixed: the deploy script reads only the keys it needs without executing the file; `.env` is written owner-only (0600). Found by running `live.sh` from a fresh clone against a Sepolia fork. Test: `test_password_file_is_owner_only_and_deploy_reads_env_without_running_it` |
| J9 | A judge who copied `.env.example` and filled in only a Qwen key got a console that crashed at start: the example set `TIWALA_LLM_PROVIDER=deepseek` with an empty DeepSeek key, and the client error was not caught. The console also forced OpenRouter whenever DeepSeek had no key, skipping a Qwen key. The live script read `.env` values with their inline comments. | Low (availability) | Fixed: Qwen Cloud is the default, empty keys count as missing, any provider error falls through to the next key, and both `.env` readers drop inline comments. Test: `test_empty_keys_from_env_example_fall_through_to_a_real_one` |

Probed and held: `//api/state`, `/API/state`, percent-encoded and `..` paths return only the static page shell or
401; `/docs` and `/openapi.json` are off; fixture names and negotiation ids are checked against strict patterns
before any file is read; one supplier's token is refused on another supplier's negotiation; the UI has no raw-HTML
sinks and the CSP allows scripts from this origin only; every `.env` value was compared with the full public git
history and none of the keys or tokens appear there; every state-changing contract function carries an owner,
operator or platform modifier.

The live path was walked the same way: `./scripts/live.sh` from a fresh clone against a Sepolia fork (archive RPC,
fresh funded key, no other setup), including a run interrupted mid-deployment, the rerun after it, and a second run
that reuses the deployment. Besides J8 it showed that a fresh live deployment had no simulated supplier side, so the
Negotiations tab had nothing to negotiate with; `live.sh` now seeds the same labelled Lumen agent and Bayani
simulator as the local demo. With only an OpenRouter key, a negotiation, escrow, deposit, attestation and balance
release all completed.

Supplier chat was then run end to end through the console against local stand-ins for the Telegram Bot API and
Meta's Graph API: invite link, Start, opening offer, free-text reply, exact-code acceptance, escrow and the
confirmation in the supplier's chat; for WhatsApp also Meta's verify handshake and signed replies through the
tunnel gate, the `hello_world` template first and the held offer released on the reply. Design change: a number
the owner links in the signed-in console is allowed to receive messages; `WHATSAPP_ALLOWED_RECIPIENTS` is now an
optional extra restriction rather than a second required list. Linking stays owner-only, and STOP still opts out.

Accepted for this deployment model: the global login lockout (30 failures in 15 minutes) can be triggered by anyone
who can reach the login page, which would lock the owner out for 15 minutes. The console is meant to stay local, and
the tunnel script exposes only the webhook, so the login is not reachable from the internet in the documented setup.
Supplier tokens do not expire and are revoked together (delete `supplier_token_secret`). A Telegram invite is a
bearer link until it is used: whoever presses Start first becomes that supplier's chat. The supplier is told when
a chat is linked, and negotiations already open stay bound to the identity they started with.

## Deployment model

The console runs on the owner's machine and binds to `127.0.0.1`. It is not meant to be exposed whole. Receiving
live WhatsApp replies needs a public HTTPS URL for `/webhooks/whatsapp` only (signed by Meta with the app secret);
expose that one path through a tunnel or reverse proxy for as long as it is needed and keep every other path local.
`scripts/whatsapp-tunnel.sh` does this: the tunnel reaches a small gate that forwards only `/webhooks/whatsapp`
([`docs/whatsapp-webhook.md`](docs/whatsapp-webhook.md)). Telegram needs no inbound connection at all.
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
- **Reputation is computed off-chain from on-chain events.** Each time it is needed, the agent reads every deal
  outcome (on time, late, cancelled after a deposit, disputes) emitted by factory wallets on Sepolia through a public
  RPC endpoint; nothing is hard-coded. The starting history is seeded: the deploy script creates four network
  buyer wallets and records synthetic trades so suppliers have a record. Treat those scores as demo data, not
  independent trade history (audit F4). A bug in `reputation.py` could set a wrong cap; the contract's
  `maxDownBps` is the hard ceiling.
- **Sybil resistance comes from onboarding, not from the score.** `createWallet` is `onlyPlatform`, so only buyers
  the platform admits can record outcomes. The reputation formula itself would credit any wallet that trades.
- **Reputation size weighting (fixed 20 October 2026).** Each outcome used to count `min(3, total / median)` for wins
  and losses alike, so a supplier failing only small orders kept a 45% deposit cap where the same record failing
  large ones got 15%. Wins now count at most 1 and failures at least 1, so failing small earns no more than an
  honest record (30%). The four demo suppliers' caps are unchanged. Test:
  `test_failing_only_small_orders_does_not_buy_a_higher_cap`
- **No recency decay.** Outcomes carry a block and log index but no age weight, so a record from long ago counts
  the same as last week's.
- **Forecast inflows are the owner's own assertions.** `data/plans.json` receivables have no haircut, so one
  optimistic inflow can hide a shortfall. The file is read-only at runtime (only `setup_data.py` writes it), so no
  model or injected text can change it.
- **LLM provider sees conversation content, minimised.** Phones, e-mails and account numbers are masked and wallet
  addresses replaced by placeholders before any model call (`privacy.py`); names, amounts and dates still go to the
  provider.
- **Timestamps.** Deadlines use `block.timestamp`; drift of seconds does not matter at hour and day granularity.
- **Single chain, test token, no upgrade path.** Contracts are not upgradeable; a fix means a new deployment.
- **Supplier side.** Real suppliers join through WhatsApp, the supplier web page or the supplier API
  ([`docs/supplier-api.md`](docs/supplier-api.md)), each authorised by a per-supplier token (HMAC of the address
  under a key in the buyer's data directory; revoke all by deleting that key). The "supplier agent" option is a
  simulated supplier that runs on the buyer's server with its own private mandate, for demos and tests; it is not
  another party's agent.
- **No wallet connect.** Buyer wallets are created by the platform through the factory, and the console signs with
  the owner and agent keys configured on the device. A visitor cannot attach their own browser wallet.
- **Local demo without a model key** (`scripts/local-demo.sh`) replaces the model Checker with a labelled
  rules-only pass so payments can be tried; intent, policy, Gate and contract checks still apply. Outside that
  explicit setting, a missing model key makes the Checker fail closed.
