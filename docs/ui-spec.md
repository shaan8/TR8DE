# TR8DE agent console: UI spec

Sources: `agent/logs/audit.jsonl` (counted 2026-10-18), `reports/live/*.txt`, `docs/demo-runbook.md`.
Criteria: **T** task completion 40%, **S** security and compliance 30%, **I** innovation and interaction 30%.

## 1. Screen states

| # | State | Demo beat | Raw source | What the screen must show | Proves |
|---|---|---|---|---|---|
| 1 | Empty / first load | 1 | wallet_state | Wallet split free vs locked, daily limit left, open deals, "Nothing needs you" | T (asset management) |
| 2 | Loading, step by step | all | event order in a turn | Live pipeline: guard, Coordinator, Checker, policy, signer, each ticking as it finishes | I |
| 3 | Clarifying question | 4b | beat4b transcript | Agent question with the missing field named; no action card | I |
| 4 | Approval needed (Tier 2) | 2 | `verdict` tier2 conf=true (2 logged) | ActionCard: supplier, R, cap math (network cap, stranger cap, final), DP and balance, forecast impact, flags, Checker verdict, Confirm / Edit | T, S, I |
| 5 | Correction re-checked | 2 | ledger "OK, make it 20% down" then new verdict | Card diff: old vs new terms, re-run checks | I |
| 6 | Executed with receipt | 2, 3 | `executed` (7 logged) | TxReceipt: action, deal id, block, Etherscan link, status | T |
| 7 | Owner-key action | 3 | `owner_command` (/attest) | Owner badge, separate from agent actions, tx link | S |
| 8 | Autonomous action | 3, 5 | `monitor_tick` notes, Tier 1 verdicts with origin monitor | Activity feed entry: rule fired, Tier 1, tx; not in chat | T, I |
| 9 | Injection caught | 4a | beat4ac transcript, `raw_address` guard flags (3 logged) | Untrusted text quoted in a "from chain, treated as data" block; flag chip | S |
| 10 | Refused (Tier 3) | 4b, 4d | `verdict` tier3 allowed=false (5 logged) | RefusalCard: rule that refused, flags (checker_reject, intent_mismatch), no Confirm | S |
| 11 | Intent mismatch | 4d | tier3 with intent_mismatch (1 logged) | Owner's words vs drafted action, the mismatched field highlighted | S, I |
| 12 | Contract revert | 4c | beat4c transcript (cast, not agent) | Receipt with status Reverted, decoded `WrongStatus(Locked)` | S |
| 13 | Rate-limited / model down | any | `coordinator_error` 429 (1 logged) | Calm banner: nothing was drafted, nothing moved, retry | I (graceful failure) |
| 14 | Shortfall alert | 2, 5 | monitor note "planned POs leave you ₱75,000 short" | "Needs you" alert with date and amount | T, I |
| 15 | Reputation update | 5 | beat5 transcript (Bayani cap 15%) | Supplier row showing the cap dropped after non-delivery | I |
| 16 | Halted (underfunded / paused) | none | `monitor_halt` (0 logged) | Red system banner; all actions disabled. Synthetic fixture, labelled as such | S |
| 17 | New payee from your words | 6 | `payee_check` allowed (1 logged) | Every payee check, chunked address, last-4 input, "Sign with owner key" | S, I |
| 18 | Payee signed by owner key | 6 | `payee_saved` (1 logged) | Owner-key receipt, Etherscan tx, "Payable from" after the 24-hour `supplierDelay` | S |
| 19 | Payee in waiting period | 6 | verdict refused, cooling period (1 logged) | Deal to the new payee refused until the contract's waiting period ends | S |
| 20 | Lookalike address refused | 6 | `payee_check` refused, `lookalike_address` (1 logged) | Address-poisoning pattern named: same first and last 4 characters as Bayani | S, I |
| 21 | Address from chain text | 6 | model declines, no draft (2 logged) | Owner asks to save the address in deal 3's PO note; the model refuses. Code's provenance check is the tested backstop | S |

States 12, 15 and 16 have no audit event; their fixtures come from the transcripts or are marked synthetic.

## 2. Stack

| Option | Estimate | Ceiling |
|---|---|---|
| Streamlit + custom HTML components | 3 to 4 h | Full reruns flash on every click, no streaming of pipeline steps, weak at 390px, cards cannot hold their own Confirm/Edit state cleanly |
| **FastAPI over `TR8DE` + small React page (Vite, Tailwind, shadcn-style components)** | 5 to 7 h | Needs a node build; one more process to run |

**Recommendation: FastAPI + React.** Each state above is a component with its own props, fixtures replay through
the same API the live agent uses, steps stream over SSE, and Playwright/axe work against a normal page. Keep the
current Streamlit app as the fallback for recording until the new console passes its checks.

API sketch: `GET /api/state` (wallet, deals, pending, alerts) · `POST /api/message` (SSE stream of events,
then reply) · `POST /api/confirm` · `POST /api/tick` · `GET /api/verify` · `?fixture=<name>` on all of them replays
`audit.jsonl` slices with no LLM or chain calls.

## 3. Design tokens

Contrast measured with the WCAG 2 formula. AA: 4.5:1 body text, 3:1 large text and UI boundaries.

| Token | Hex | Role | Contrast on canvas / raised |
|---|---|---|---|
| `bg.canvas` | #0F0E47 | Page | n/a |
| `bg.surface` | #1B1A52 | Panels, sidebar | n/a |
| `bg.raised` | #272757 | Cards, inputs | n/a |
| `border.subtle` | #505081 | Dividers only (decorative) | 2.4 / 1.9: never for text or required boundaries |
| `accent` | #8686AC | Large text, icons, focus ring, selected | 5.1 / 4.0: body text only on canvas |
| `accent.text` | #A9A8D9 | Links and accent body text on any surface | 7.9 / 6.1 |
| `text.primary` | #F2F2F8 | Body and headings | 16.0 / 12.4 |
| `text.secondary` | #B9B8D6 | Labels, metadata | 9.3 / 7.2 |
| `success` | #6FD3A0 | Executed, approved, Tier 1 | 9.8 / 7.6 |
| `warning` | #F2C14E | Needs you, Tier 2, shortfall | 10.7 / 8.3 |
| `danger` | #FF8A80 | Refused, reverted, halted, Tier 3 | 7.8 / 6.1 |

Status never relies on color alone: every chip carries its word (Approved, Refused, Tier 2).

Type scale (px / line height): 12/16 caption · 14/20 body small · 16/24 body · 20/28 card title · 28/36 section ·
40/48 headline. Font: Inter or IBM Plex Sans; IBM Plex Mono for hashes and amounts.

Spacing on an 8px grid: 4 (hairline only), 8, 16, 24, 32, 48, 64. Radius 8 (chips 999). Card padding 24.
Breakpoints: 1440 (sidebar + feed + chat), 1024 (feed collapses under chat), 390 (single column, "Needs you" first).

## 4. Layout

- **Left (surface):** wallet split, daily limit, deals table showing each deal's lifecycle stage (Locked, DP paid, Delivered, Completed, Refunded, Disputed).
- **Centre:** "Needs you" strip (pending ActionCards, shortfall and halt alerts) above the chat; agent replies hold
  ActionCard / RefusalCard / TxReceipt components, each with a collapsible agent trace.
- **Right:** activity feed of autonomous actions and owner-key actions, newest first, each with its receipt.

## 5. Acceptance

- Every state in section 1 renders from a fixture with zero LLM and chain calls.
- Playwright screenshots of each state at 1440 and 390 widths saved to `reports/ui/`.
- axe: 0 serious or critical violations.
- Every tx hash and amount on screen matches `audit.jsonl` and Etherscan.
- A silent 5-second test of each beat: a viewer can say what the agent did and why it was allowed or blocked.
