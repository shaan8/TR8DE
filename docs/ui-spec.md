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

From the TR8DE workspace design (dark green). Contrast measured with the WCAG 2 formula. AA: 4.5:1 body text, 3:1
large text and UI boundaries. The design's smallest labels were raised to 11 px and its dimmest greys lightened so
every text colour passes AA.

| Token | Hex | Role | Contrast on canvas / raised |
|---|---|---|---|
| `bg.canvas` | #111411 | Page | n/a |
| `bg.surface` | #151915 | Sidebar, treasury panel | n/a |
| `bg.raised` | #1c2318 | Cards, user messages | n/a |
| `border.subtle` | #343e2c | Dividers only (decorative) | 1.7 / 1.4 |
| `accent` | #c4df9b | Brand 8, primary button, links, focus ring, selected | 12.7 / 11.0 |
| `text.primary` | #e6e9e0 | Body and headings | 15.1 / 13.1 |
| `text.secondary` | #a3ab9b | Labels, metadata | 7.8 / 6.8 |
| `success` | #a9d37f | Executed, approved, Tier 1 | 10.9 / 9.4 |
| `warning` | #d9c27f | Needs you, Tier 2, shortfall | 10.6 / 9.2 |
| `danger` | #eba08b | Refused, reverted, halted, Tier 3 | 8.8 / 7.6 |

Status never relies on color alone: every chip carries its word (Approved, Refused, Tier 2).

Type scale (px / line height): 11/16 micro · 12/17 caption · 13/20 small · 14/22 body · 17/24 title · 26/34 section.
Fonts: DM Sans for text, Manrope for the brand, headings and amounts, IBM Plex Mono for hashes and addresses.

Radius 7 (cards 9). Breakpoints: 1024 and up (sidebar, chat, treasury panel side by side), 768 (sidebar behind a
menu button), 390 (single column, "Needs you" first, treasury panel under the chat).

## 4. Layout

- **Left sidebar:** brand, workspace navigation (Agent workspace, Payments, Negotiations, Suppliers), quick prompts
  that fill the composer, connection status and sign-out.
- **Centre:** "Needs you" bar (pending cards, payees, shortfall and halt alerts) above the conversation; agent replies
  hold the approval card, refusal card and receipts, each with a collapsible "Checks complete" trace; the composer
  with suggested prompts and Run monitor sits at the bottom.
- **Right, Treasury overview:** wallet total with the available and locked split, the agent's daily limit and
  on-its-own threshold, tabs for Activity (autonomous and owner-key actions, newest first), Escrows and Payees, and
  the agent team with the model running each role.
- **Suppliers:** saved payees with on-chain status, linked chat channel and contact controls. **Supplier console:**
  the same shell without owner navigation, showing only the supplier's mandate and negotiations.

## 5. Acceptance

- Every state in section 1 renders from a fixture with zero LLM and chain calls.
- Playwright screenshots of each state at 1440 and 390 widths saved to `reports/ui/`.
- axe: 0 serious or critical violations.
- Every tx hash and amount on screen matches `audit.jsonl` and Etherscan.
- A silent 5-second test of each beat: a viewer can say what the agent did and why it was allowed or blocked.
