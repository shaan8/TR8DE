# Tiwala

AI escrow wallet agent for MSME supplier payments (WeBank Fintechathon 2026, International Track, Topic F).
Three LLM agents plan and check; deterministic code decides; the contract has the final say.

Live on Sepolia: factory [`0xDEF343...d569`](https://sepolia.etherscan.io/address/0xDEF343FeeD80C2Dd4943B731bde56bb8932Bd569),
demo wallet [`0x2Fc37E...8C1a`](https://sepolia.etherscan.io/address/0x2Fc37E4e02F4d10745875710cd54B52429A28C1a).
Full deploy log (111 txs, 0 reverted): [`reports/sepolia-evidence.md`](reports/sepolia-evidence.md).
Security self-assessment: [`SECURITY.md`](SECURITY.md).
Source: https://github.com/shaan8/TR8DE

## Layout

| Path | What |
| --- | --- |
| `src/` | `TiwalaAgentWallet` (escrow, owner/agent tiers), `TiwalaFactory` (platform-gated, account-hash dedup), `SettlementToken` (tPHP, 2 decimals) |
| `test/` | 42 Foundry tests (38 unit, 1 fuzz, 3 invariant) |
| `script/` | `Deploy.s.sol` (deploy + seed network history), `Finish.s.sol` (close the 2 late deals) |
| `scripts/` | `deploy-sepolia.sh` (one-command deploy), `evidence_table.py` (builds the evidence report from broadcasts) |
| `agent/tiwala_agent/` | Agent core (Python) |
| `agent/tests/` | 102 tests: deterministic layer, account connectors, end-to-end red-team on anvil |
| `reports/` | Test, coverage and Slither output; `live/` holds live agent transcripts and the audit log |

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
| `connectors.py` | Read-only balances from banks (Plaid), PayPal and Stripe; encrypted vault | no |
| `chain.py` | Indexer (factory wallets only), simulator, scoped agent signer, owner console | no |
| `audit.py` | Hash-chained, redacted JSONL audit log | no |

Guarantees enforced in code: the Coordinator can only draft; execution needs a Gate authorization minted after the
policy engine allows it; Tier 2 confirmation is matched on the owner's own next message; owner-tier actions
(`/attest`, `/approve`, `/dispute`, `/resolve`) run only from typed commands; the Checker fails closed.

## Live agent run on Sepolia

All five demo beats ran end to end against the deployed contracts. Transcripts are in [`reports/live/`](reports/live/);
`audit.jsonl` (69 entries) verifies as an intact hash chain.

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

The UI (`agent/app.py`) reads `../.env` itself and shows free vs locked funds, read-only connected accounts,
the agent's daily limit left and open deals beside the chat. It uses OpenRouter when no DeepSeek key is set.

### Agent console (FastAPI + React)

```bash
cd ui && npm install && npm run build                                # builds ui/dist
cd ../agent && ../.venv/bin/uvicorn console.server:app --port 8000   # API + page on :8000
```

Open `http://127.0.0.1:8000/?fixture=approval` (or pick any of the 17 states in the header) to replay
`agent/logs/audit.jsonl` slices and `reports/live` transcripts with no model or chain calls. Without
`?fixture=` the page drives the live agent. `cd ui && npm run shots` renders every state at 1440 and 390 into
`reports/ui/` and runs axe on each (spec: `docs/ui-spec.md`).

### Connected accounts

**Connect account** in the UI links an off-chain account so the forecast sees the owner's whole cash position.
Tiwala reads balances only; money moves only through the on-chain escrow. Balances come only from the
providers' read-only APIs: there is no manual entry, and no amount is stored on disk or accepted from a user,
a file or a model.

| Provider | What the owner supplies | API | Read-only enforcement |
| --- | --- | --- | --- |
| Banks via Plaid (US, CA, UK, EU) | Picks a bank (sandbox) or logs in through Plaid Link (production) | `/accounts/balance/get` | Plaid access token with no money-movement product; revoked at Plaid on unlink |
| PayPal | Their REST app's client ID and secret | `GET /v1/reporting/balances` | Link refused without the reporting read scope; extra payment scopes shown as a warning |
| Stripe | A restricted key with only Balance: Read | `GET /v1/balance` | Full `sk_` keys refused; a probe refuses any key that can also read charges |

Balances are fetched live over pinned HTTPS and held in memory for two minutes. `links.json` holds only link
metadata, so editing it cannot create a balance; balances older than 24 hours are left out. Credentials are
Fernet-encrypted in `agent/data/vault.bin` and never reach the LLM or the audit log. Non-PHP balances use
indicative rates fixed in code, for the forecast only.

Sandbox setup (free): Plaid keys from dashboard.plaid.com into `.env` (`PLAID_CLIENT_ID`, `PLAID_SECRET`);
a PayPal sandbox business app with Transaction Search enabled; a Stripe test-mode restricted key. Stripe test
balances start at zero until you make a test charge with card `4000 0000 0000 0077` (funds available at once).
Alipay and WeChat Pay expose balance queries only to approved merchant accounts, so they slot in as further
adapters once a merchant account exists.

Owner commands: `/attest N`, `/approve N`, `/dispute N`, `/resolve N release|refund`, `/tick` (run the monitor),
`/verify` (check the audit chain), `/quit`.
Deadlines accept `YYYY-MM-DD` (23:59) or `YYYY-MM-DD HH:MM` in the device timezone (`TIWALA_TZ` overrides).

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
