# TR8DE

[![CI](https://github.com/shaan8/TR8DE/actions/workflows/ci.yml/badge.svg)](https://github.com/shaan8/TR8DE/actions/workflows/ci.yml)

AI escrow wallet agent for MSME supplier payments (WeBank Fintechathon 2026, International Track, Topic F).
Three LLM agents plan and check; deterministic code decides; the contract has the final say.
TR8DE was called Tiwala during development: the Python package (`tiwala_agent`), the `TIWALA_*` settings and the
deployed contract names (`TiwalaAgentWallet`, `TiwalaFactory`) keep that name, so the Sepolia evidence still matches.

Live on Sepolia: factory [`0xDEF343...d569`](https://sepolia.etherscan.io/address/0xDEF343FeeD80C2Dd4943B731bde56bb8932Bd569),
demo wallet [`0x2Fc37E...8C1a`](https://sepolia.etherscan.io/address/0x2Fc37E4e02F4d10745875710cd54B52429A28C1a).
Full deploy log (111 txs, 0 reverted): [`reports/sepolia-evidence.md`](reports/sepolia-evidence.md).
Security self-assessment: [`SECURITY.md`](SECURITY.md).
Submission map (every deliverable and where to find it): [`SUBMISSION.md`](SUBMISSION.md). Execution evidence: [`reports/evidence/SUMMARY.md`](reports/evidence/SUMMARY.md).
Source: https://github.com/shaan8/TR8DE

## Two ways to run it

| | Demo (local) | Live (Sepolia) |
| --- | --- | --- |
| Chain | A private Ethereum chain on your machine | Sepolia, Ethereum's public test network |
| You need | git, Node 18+, Python 3.11+ | The same, plus 0.02 Sepolia test ETH from a free faucet and a model key (Qwen Cloud) |
| Setup time | About 2 minutes | About 50 minutes the first time, then instant |
| Proof | Disappears when you stop it | Public transactions anyone can open on Etherscan |

**Keys and accounts.** Copy `.env.example` to `.env` and fill in only what you need:

| What | Needed for | Where to get it |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` (Qwen Cloud, the default model) | The chat assistant in both modes; payments in live mode | [Qwen Cloud](https://www.alibabacloud.com/en/product/modelstudio) console, or `python3 scripts/setup_qwen.py` to paste it privately. DeepSeek, OpenRouter (free models) or Anthropic keys also work; the first key present is used |
| Sepolia test ETH, 0.02 | Live mode only | Free from a faucet; `live.sh` makes the key and prints the address to fund (step 2 below). Nothing to mine yourself |
| `TELEGRAM_BOT_TOKEN`, plus `TELEGRAM_LIVE_SEND=1` | Optional, live mode: real supplier chat on Telegram | Message @BotFather in Telegram, send `/newbot`. Setup: [`docs/telegram.md`](docs/telegram.md) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ALLOWED_RECIPIENTS`, plus `WHATSAPP_LIVE_SEND=1` | Optional, live mode: real supplier chat on WhatsApp | A Meta developer app with the WhatsApp product. Setup: [`docs/whatsapp-webhook.md`](docs/whatsapp-webhook.md). The built-in WhatsApp simulator needs none of this |

With a bot token or WhatsApp keys set, connect a supplier from the Negotiations tab ("Invite on Telegram" or "Link
WhatsApp") or with `/invite NAME` and `/whatsapp NAME NUMBER` in the chat, then negotiate: offers go to their chat,
their replies come back, and only an exact `ACCEPT <code>` from them counts. The local demo never sends real
messages, whatever `.env` says. The local demo needs none of them. Without a model key the chat is off, but negotiations, escrow and owner
commands still run.

### Demo: one command, no accounts

```bash
git clone https://github.com/shaan8/TR8DE.git && cd TR8DE && ./scripts/local-demo.sh
```

The script installs what it needs, starts a private chain, deploys the same contracts used on Sepolia with
seeded suppliers and trade history, and opens the console with a one-time login it prints. Ctrl+C stops it.

In the demo, messaging is switched off on purpose, so a throwaway demo can never text anyone: WhatsApp and Telegram
settings in `.env` are ignored, and supplier chat runs in the built-in WhatsApp simulator instead. Real WhatsApp and
Telegram messages work in live mode.

Then try (all of this works without a model key):

1. Negotiations tab: start one with Lumen (simulated supplier agent) or Bayani (WhatsApp simulator, where you type
   as the supplier). When both sides agree, press "Recheck and prepare escrow", then confirm with "yes" in
   Payments. The full amount is locked on the chain, the down payment goes out, and the reply names the deal number.
2. Payments: `/attest <deal>` with that number to confirm delivery. The balance is released and Lumen's record
   updates from the chain.
3. Your own supplier agent: the script prints a command for
   [`scripts/supplier_agent_example.py`](scripts/supplier_agent_example.py); see [`docs/supplier-api.md`](docs/supplier-api.md).
4. With a model key in `.env`, ask in plain words: "Create escrow for Lumen PO-104, PHP 120,000, 20% down,
   delivery in 10 days", then reply "yes". Without a key the chat says it is off; owner commands still work.

Red-team notes, what we tried and what was fixed: [`SECURITY.md`](SECURITY.md#judge-walkthrough-19-october-2026).

**What the demo can and cannot do, compared with live**

| | Demo | Live |
| --- | --- | --- |
| Contracts, limits, escrow, deposits, attestation, refunds | Same contracts and rules | Same |
| Transactions | On a throwaway chain; hashes are not public proof | On Sepolia; every hash opens on Etherscan |
| Supplier reputation | Read from the chain, from seeded history plus your demo deals | Read from Sepolia, from seeded history plus your real test deals |
| Keys | Public Anvil test keys (worthless) | Your own keys, kept in `.env` |
| Paying addresses outside the demo | No: only addresses on the local chain | Yes: any Sepolia address you save as a payee, payable after a 10-minute waiting period (`PAYEE_DELAY`; 24 h in production) |
| WhatsApp | Built-in simulator only; never sends, whatever `.env` says | Real messages both ways with Meta credentials ([docs/whatsapp-webhook.md](docs/whatsapp-webhook.md)) |
| Telegram | Off; never sends, whatever `.env` says | Real messages both ways with a bot token; no public URL needed ([docs/telegram.md](docs/telegram.md)) |
| Without a model key | Chat assistant off; negotiations use rules and a scripted supplier; payments use a labelled rules-only Checker | Chat assistant off; the Checker fails closed, so no payments |
| Persistence | Everything resets on each run | Contracts and history stay on Sepolia |

### Live: your own deployment on Sepolia

1. Put a model key in `.env`: `DASHSCOPE_API_KEY` for Qwen Cloud (the default). On Sepolia the independent Checker
   fails closed without a model key, so every payment is refused. Optional: `SEPOLIA_RPC_URL` for your own RPC.
2. Run `./scripts/live.sh`. The first time, it creates a deployer key, prints its address and stops. Send that
   address 0.02 Sepolia ETH from a faucet. This is free test ETH with no value, and nothing needs to be mined
   by you. Any of these works:
   [Google Cloud](https://cloud.google.com/application/web3/faucet/ethereum/sepolia) (Google account),
   [pk910 PoW faucet](https://sepolia-faucet.pk910.de) (no account; your browser works for a few minutes),
   [Alchemy](https://www.alchemy.com/faucets/ethereum-sepolia) (needs a little mainnet ETH).
   To use a key you already have, put it in `.env` as `PRIVATE_KEY=0x...` instead. Never use one that holds real funds.
3. Run it again:

```bash
./scripts/live.sh
```

The script creates the owner and agent keys in `.env` if they are missing, deploys the token, factory and
wallets, seeds supplier history, asks you to choose a console password, and starts the console. Leave it running
for the first deployment; later runs reuse it and start in seconds. Payments, attestations and refunds then happen
as Sepolia transactions, linked to Etherscan from the console. Our own deployment and its transactions are listed
in [`reports/sepolia-evidence.md`](reports/sepolia-evidence.md).

## Layout

| Path | What |
| --- | --- |
| `src/` | `TiwalaAgentWallet` (escrow, owner/agent tiers), `TiwalaFactory` (platform-gated, account-hash dedup), `SettlementToken` (tPHP, 2 decimals) |
| `test/` | Foundry unit, fuzz and invariant tests (run in CI) |
| `script/` | `Deploy.s.sol` (deploy + seed network history), `Finish.s.sol` (close the 2 late deals) |
| `scripts/` | `deploy-sepolia.sh` (one-command deploy), `evidence_table.py` (builds the evidence report from broadcasts) |
| `agent/tiwala_agent/` | Agent core (Python) |
| `agent/tests/` | Deterministic layer, negotiation, WhatsApp and supplier API, console login, red team, pentest regressions and 200k-case policy fuzz, on anvil; grouped results in [`reports/evidence/SUMMARY.md`](reports/evidence/SUMMARY.md) |
| `reports/` | Test, coverage and Slither output; `live/` holds live agent transcripts and the audit log; `negotiation/` holds recorded negotiation demos |

## Agent core

| Module | Role | LLM? |
| --- | --- | --- |
| `app.py` (in `agent/`) | Streamlit chat UI with free vs locked funds panel | n/a |
| `core.py` | Orchestrator, Gate (HMAC authorizations), Executor, confirmations, monitor tick, owner commands | no |
| `agents.py` | Coordinator, Treasury planner, Checker prompts and tools | yes |
| `llm.py` | Providers: DeepSeek (default), OpenRouter, Anthropic | n/a |
| `policy.py` | Policy engine + risk flags, tiers 0 to 3 | no |
| `intent.py` | Intent verifier: action vs the owner's own words | no |
| `guard.py` | Input guard: source tagging, injection flags, contract text wrapped as data | no |
| `reputation.py` | Network reputation, buyer-history weight, DP cap, 25% stranger cap | no |
| `forecast.py` | Liquidity forecast H(t) and candidate fixes | no |
| `chain.py` | Indexer (factory wallets only), simulator, scoped agent signer, owner console | no |
| `audit.py` | Hash-chained, redacted JSONL audit log | no |
| `payee.py` | Payee checks before an owner-key `addSupplier` | no |
| `negotiation.py` | Versioned proposals, terms hashes, state machine, buyer checks and strategy | suggests only |
| `supplier_agent.py` | Supplier mandate and agent (live model or scripted), checked in code | optional |
| `whatsapp.py` | WhatsApp Cloud API adapter (webhook, signature, dedup, window, opt-in) and local simulator | no |
| `telegram.py` | Telegram bot adapter on the same Gateway: long polling, one-time start-link binding, /stop | no |
| `negotiation_service.py` | Fresh buyer views from chain, idempotent escrow handoff | no |

Guarantees enforced in code: the Coordinator can only draft; execution needs a Gate authorization minted after the
policy engine allows it; a new deal is created by the agent alone only within the contract's own
`approvalThreshold`, and needs the owner above it; Tier 2 confirmation is matched on the owner's own next message; owner-tier actions
(`/attest`, `/approve`, `/dispute`, `/resolve`) run only from typed commands; the Checker fails closed.

## Live agent run on Sepolia

All six demo beats ran end to end against the deployed contracts. Transcripts are in [`reports/live/`](reports/live/);
`audit.jsonl` (93 entries) verifies as an intact hash chain.

| Beat | What happens | Evidence |
| --- | --- | --- |
| 1. Onboarding | Network history seeded across 4 buyer wallets and 4 suppliers | [`reports/sepolia-evidence.md`](reports/sepolia-evidence.md) |
| 2. Happy path | Owner asks for 30% down to Lumen; network caps it at 25%; deal created, down payment released | [create](https://sepolia.etherscan.io/tx/0xc26642d49f9e7079171076a8c5f6cf9f3c7b23537acc64b4aa4017b1200f953c), [down payment](https://sepolia.etherscan.io/tx/0xfb10145647f17ce77194b5a15bb5934b2fd3107b359674180e66f06a9be407de), [transcript](reports/live/beat2-happy-path.txt) |
| 3. Milestone | Owner attests delivery (owner key), agent releases balance at Tier 1 | [attest](https://sepolia.etherscan.io/tx/0xb6a31fd50869448423ed8a9de70d7894c3ef7aafa51006d8d4787f1f4cb118e9), [release](https://sepolia.etherscan.io/tx/0x1862184b830f168131b8177215a10353a271eee28396d7b7aa2a357cb433e9d1), [transcript](reports/live/beat3-milestone.txt) |
| 4a. Prompt injection | Instruction planted in an on-chain PO note; agent treats it as data and refuses to release without attestation | [planted note](https://sepolia.etherscan.io/tx/0x06a326cfda226cca1dce0369e1118e9f1eaecfa831db75d6fa1b52926dacf205), [transcript](reports/live/beat4ac-inject-and-release.txt) |
| 4b. Unknown payee | Agent cannot pay an unregistered supplier | [transcript](reports/live/beat4b-new-address.txt) |
| 4c. Contract backstop | Agent key forces `releaseBalance` on an unattested deal; contract reverts `WrongStatus(Locked)` | [reverted tx](https://sepolia.etherscan.io/tx/0x0479cd2d2ea18c2403a90278ef526e0adb5b04bf2365f3cb3088606a4e5168d0), [transcript](reports/live/beat4c-forced-revert.txt) |
| 4d. Social engineering | Owner pushes for 50% down; policy holds the 25% cap, Checker flags the changed terms | [transcript](reports/live/beat4d-manipulation.txt) |
| 5. Overdue | Bayani misses the deadline; monitor tick refunds at Tier 1; Bayani's cap drops to 15% | [create](https://sepolia.etherscan.io/tx/0x47d2f33dbe583bf674a39a7e03290843a5ad3d44a17cd35434feb11718aba1b7), [down payment](https://sepolia.etherscan.io/tx/0x8ae244f155da26305d8ce3dec956a3cf6bc8378dc144f90182a370b0a3ac42e3), [refund](https://sepolia.etherscan.io/tx/0xb16c7e1fb84a082e5efa60336faace9a99e3713020b7321245758fcbe5c212e7), [transcript](reports/live/beat5-overdue.txt) |
| 6. New payee | Owner saves Kalinaw Crafts in one sentence; payee checks pass; owner types the last 4 characters and the owner key signs `addSupplier`; a deal before the 24-hour waiting period is refused; a poisoned lookalike of Bayani's address and an address from a PO note are refused | [addSupplier](https://sepolia.etherscan.io/tx/0x9a95283c0a3880fc06a7253858ae2a2c784edd01cdb270191932abf06a723111), transcripts [save](reports/live/beat6-save-payee.txt), [too soon](reports/live/beat7-pay-too-soon.txt), [lookalike](reports/live/beat8-lookalike-payee.txt), [from chain](reports/live/beat9-payee-from-chain.txt) |

## Run the tests

```bash
npm install                      # forge, anvil, cast (via @foundry-rs) + OpenZeppelin
git clone --depth 1 https://github.com/foundry-rs/forge-std lib/forge-std
forge test                       # contracts
python3 -m venv .venv && .venv/bin/pip install -r agent/requirements.txt
cd agent && ../.venv/bin/python -m pytest -q   # agent; integration tests need anvil + forge on PATH
```

## Deploy to Sepolia

```bash
cp .env.example .env             # fill SEPOLIA_RPC_URL, PRIVATE_KEY (funded), OWNER/AGENT keys, ACCOUNT_SALT
./scripts/deploy-sepolia.sh      # deploys, seeds history, waits for the late window, closes the late deals
```

Addresses land in `deployments/11155111.json`; every tx hash is in `broadcast/*/11155111/run-latest.json`.
Budget roughly 0.1 to 0.3 Sepolia ETH (about 110 transactions; depends on gas price).

## Run the agent

The agent reads event logs over wide block ranges. Use an RPC without a tight `eth_getLogs` limit
(Alchemy free tier allows 10 blocks; it works, slowly).

```bash
set -a; source .env; set +a
export RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
cd agent
../.venv/bin/python -m tiwala_agent.setup_data ../deployments/11155111.json data/
../.venv/bin/streamlit run app.py                                                     # chat UI + funds panel
../.venv/bin/python -m tiwala_agent.cli --deployment ../deployments/11155111.json       # terminal
../.venv/bin/python -m tiwala_agent.drive --deployment ../deployments/11155111.json "What's open?" "/tick"   # scripted
```

The UI (`agent/app.py`) reads `../.env` itself and shows free vs locked funds,
the agent's daily limit left and open deals beside the chat. It uses OpenRouter when no DeepSeek key is set.

### Agent console (FastAPI + React)

```bash
cd ui && npm install && npm run build                                # builds ui/dist
cd ../agent && ../.venv/bin/uvicorn console.server:app --port 8000 --no-access-log   # API + page on :8000
```

Open `http://127.0.0.1:8000/?fixture=approval` (or pick any of the 21 states in the header) to replay
`agent/logs/audit.jsonl` slices and `reports/live` transcripts with no model or chain calls. Without
`?fixture=` the page drives the live agent. `cd ui && npm run shots` renders every state at 1440 and 390 into
`reports/ui/` and runs axe on each (spec: `docs/ui-spec.md`).

The console runs the monitor on its own clock every `MONITOR_INTERVAL_S` seconds (default 300, `0` turns it off),
so overdue refunds and the underfunded halt do not wait for anyone to open the page. `/tick` runs it on demand.

`/guide` lists what TR8DE can do with example prompts (no model call). Owner commands: `/attest N`, `/approve N`, `/dispute N`, `/resolve N release|refund`, `/tick` (run the monitor),
`/verify` (check the audit chain), `/quit`.
Deadlines accept `YYYY-MM-DD` (23:59) or `YYYY-MM-DD HH:MM` in the device timezone (`TIWALA_TZ` overrides).

### Supplier negotiation

Open `http://127.0.0.1:8000/?view=negotiate`. TR8DE negotiates quantity, price, deposit and delivery with a supplier
on WhatsApp (or the local simulator) or with the supplier's agent, then carries the exact agreed terms into escrow
through the same policy, Checker, Gate and your own yes. Replays: `?view=negotiate&fixture=neg_success` (also
`neg_ready`, `neg_escrow`, `neg_impossible`, `neg_injection`) and `?view=supplier&fixture=neg_success`.
Design, trust model, WhatsApp policy notes and limitations: [`docs/negotiation.md`](docs/negotiation.md). Telegram
setup (no webhook needed): [`docs/telegram.md`](docs/telegram.md). Live WhatsApp replies on a laptop, through a
webhook-only tunnel: [`docs/whatsapp-webhook.md`](docs/whatsapp-webhook.md).

For a local demo without Meta credentials:

```bash
curl -s -X POST 127.0.0.1:8000/api/sim/whatsapp/contact -H 'Content-Type: application/json' -d '{"supplier":"<payee address>","text":""}'
```

registers the simulator as that supplier's WhatsApp (labelled "simulator" everywhere) and returns its supplier-console
link. `TIWALA_SUPPLIER_AGENT=scripted` uses the deterministic supplier agent (labelled "scripted, not AI");
`TIWALA_NEGOTIATOR=rules` turns off buyer-side model calls.

### LLM providers

| `TIWALA_LLM_PROVIDER` | Key | Coordinator | Treasury | Checker |
| --- | --- | --- | --- | --- |
| `deepseek` (default) | `DEEPSEEK_API_KEY` | `deepseek-flash` | `deepseek-flash` | `deepseek-v4-pro` |
| `openrouter` | `OPENROUTER_API_KEY` | `nvidia/nemotron-3-ultra-550b-a55b:free` | same | same |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | `claude-haiku-5-5` | `claude-haiku-5-5` |

Override per agent with `TIWALA_COORDINATOR_MODEL`, `TIWALA_TREASURY_MODEL`, `TIWALA_CHECKER_MODEL`.
The Checker should run on a different model from the Coordinator so one model's blind spot cannot pass its own plan.
OpenRouter's free tier allows 50 requests a day and returns short bursts of 429s; the client backs off on
`Retry-After` and stops on the daily quota. In `.env`, write keys with no space after `=`.

### Qwen Cloud

Run `python3 scripts/setup_qwen.py` from this project. Paste your Qwen Cloud API key at the hidden
prompt. The command preserves unrelated `.env` settings and saves `DASHSCOPE_API_KEY`, the matching
Qwen Cloud endpoint (Token Plan keys `sk-sp-...` use the Token Plan endpoint), `TIWALA_LLM_PROVIDER=qwen`, and `qwen3.7-plus` for the wallet and negotiation
agents with thinking enabled. The file is written atomically with owner-only permissions and remains
ignored by Git. Restart the app after setup. No API request is made during setup.

If running the command from elsewhere, pass `--project /path/to/tiwala_SEPOLIA`.
Existing shell environment variables take precedence over `.env`; use a fresh terminal or reload
the updated file with `set -a; source .env; set +a` before launching a CLI session.

Qwen uses the existing tool-calling adapter and policy controls. Its final answer and tool calls are
used by the agent; reasoning text is not printed or written to the audit log. All roles use the same
model by default; a different Checker model can be set with `TIWALA_CHECKER_MODEL`.
