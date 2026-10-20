# Prompt for GPT (computer use): record the judge setup guide for Tiwala

Copy everything below the line into GPT with computer use enabled.

---

## Your role

You are producing a **screen-recorded, end-to-end setup guide** for hackathon judges (WeBank FinTechathon 2026,
International Track, Topic F). A judge starts with a clean Mac (or Linux, or Windows with WSL2), has never seen the
project, and must get it running locally and try its main features. You will:

1. Perform every step yourself on this computer, exactly as a judge would, starting from nothing.
2. Screen-record each step as its own short clip, with mouse movement suitable for a tutorial (rules below).
3. Write a detailed Markdown guide, `JUDGE_GUIDE.md`, that links each clip and gives the exact commands, expected
   output and fixes for anything that went wrong.

The project is **Tiwala**: an AI escrow wallet agent for small-business supplier payments. LLM agents propose
actions, deterministic code decides, and a smart contract enforces limits. The judge-facing path is a one-command
local demo that runs a private Ethereum chain on the judge's own machine. It needs no real money, no testnet faucet
and no WhatsApp account.

- Repository: https://github.com/shaan8/TR8DE
- Live Sepolia contracts (read-only evidence): factory `0xDEF343FeeD80C2Dd4943B731bde56bb8932Bd569`,
  demo wallet `0x2Fc37E4e02F4d10745875710cd54B52429A28C1a`

## Hard rules

- **Secrets never appear on screen in a finished clip.** API keys, passwords and the contents of `.env` after a key
  is pasted must be hidden. Pause the recording before revealing a key; show it only masked (for example
  `sk-or-v1-••••••••`); or cut that segment. If a key is ever visible in a recording, tell the operator so they can
  revoke it, and re-record that clip.
- **Hand off to the human operator** for anything that needs an account sign-up, a password, an email or phone
  verification, a CAPTCHA, or a payment. Stop, say exactly what you need ("Please sign in to openrouter.ai, then
  tell me to continue"), and wait. Resume recording only after the operator says to continue. In the guide, still
  describe these steps fully so a judge can do them.
- Use only the official sites named in this prompt. Do not install anything not listed here.
- Do not edit the repository's code. If something fails, record the failure and the fix or workaround, and note
  it in the guide's Troubleshooting section. Do not hide failures.
- Never use the project's live Sepolia keys or deploy anything to Sepolia. The judge path is the local demo only.

## Recording setup (do this once, before clip 01)

- macOS: turn on Do Not Disturb, hide the Dock (System Settings > Desktop & Dock > Automatically hide), close
  unrelated windows, use a plain wallpaper. Record with the built-in tool (Cmd+Shift+5 > Record Selected Portion,
  Options > Show Mouse Clicks) or QuickTime. Linux: OBS or GNOME's recorder. Windows: Xbox Game Bar or OBS.
- Display: 1440x900 or 1920x1080. Browser window maximized, zoom 110 to 125 percent so text is readable in video.
- Terminal: font size 18 or larger, high-contrast theme, window covering at least half the screen. Clear the
  screen (`clear`) before each clip.
- Save clips as `clips/NN-short-name.mov` (or `.mp4`), for example `clips/04-get-model-key.mov`. Keep every clip
  under 2 minutes; split longer steps.

## Mouse and pacing rules (tutorial quality)

- Move the pointer in smooth, direct, unhurried paths (about 0.5 to 1 second per move). No jitter, circling or
  idle wandering.
- Before each click, **pause on the target for about 1 second** so viewers can see where you are going; then click.
  After a click, keep the pointer still while the page responds.
- Point at important output (a success line, a password, a status chip) and hold for 2 seconds before moving on.
- Type at a readable pace. For long commands, paste them, then pause 2 seconds before pressing Return so viewers
  can read the command.
- Scroll slowly, in short steps. Never scroll past something you are about to talk about.
- Keep the pointer out of the way (bottom-right corner) while a command runs.
- Start each clip with 1 second of a still screen and end with 2 seconds of the result visible.

## Steps to perform and record

Each step: record a clip, then write its guide section (see "Guide format" below).

### Clip 01: Prerequisites check
Open Terminal and run:

```bash
git --version
node --version      # needs 18 or newer
npm --version
python3 --version   # needs 3.11 or newer
```

If anything is missing, install it from the official site (git-scm.com, nodejs.org LTS, python.org), and record
that in a separate clip `01b-install-prereqs`. Windows judges: note in the guide that the demo script is Bash and
must be run inside WSL2 (Ubuntu), with the same prerequisites installed there. Foundry (forge, anvil, cast) does
not need a separate install: the script uses the npm-packaged Foundry if none is on PATH.

### Clip 02: Get the code

```bash
cd ~/Desktop
git clone https://github.com/shaan8/TR8DE.git tiwala
cd tiwala
ls scripts
```

Point at `local-demo.sh` in the listing. **If `scripts/local-demo.sh` is missing, stop and tell the operator**: the
repository has not been updated yet, and the guide cannot continue until it is.

### Clip 03: Open the project and look around (30 seconds)
Briefly show `README.md`, `SUBMISSION.md` and `SECURITY.md` on GitHub in the browser (scroll the top of each),
so judges know where documentation, evidence and the security self-assessment live.

### Clip 04: Get a model API key (the most important clip; make it very clear)
The chat assistant needs one LLM API key. Show **one** provider end to end. Use OpenRouter unless the operator
tells you to use DeepSeek or Qwen:

**Option A, OpenRouter (free tier, easiest):**
1. Open https://openrouter.ai and pause on the Sign in button. Hand off to the operator to sign up or sign in.
2. After the operator says continue: go to https://openrouter.ai/settings/keys (or the profile menu > Keys).
3. Click "Create Key", give it the name `tiwala-judge`, leave the credit limit empty or small, and create it.
4. **Pause the recording**, let the operator copy the key, then resume on a screen where the key is not visible.
5. In the guide, note: free models allow about 50 requests per day, and one full demo uses roughly 20 to 40.

**Option B, DeepSeek (paid, cheapest reliable):** https://platform.deepseek.com > API keys > Create new API key.
Needs a small top-up under Billing (operator does the payment).

**Option C, Qwen (Alibaba Cloud Model Studio, DashScope):** only if the operator asks. The repo includes
`python3 scripts/setup_qwen.py`, which prompts for the key privately and writes `.env` for you. Check that the
script exists before relying on it.

### Clip 05: Create the .env file (show slowly; judges get this wrong most often)
In the terminal, from the project folder:

```bash
cp .env.example .env
open -e .env          # macOS TextEdit; on Linux use: nano .env
```

Show the file. Explain on screen (with the pointer) that for the local demo **only two lines matter**, and every
Sepolia and WhatsApp line can stay empty. Set, with no spaces around `=`:

- For OpenRouter:
  ```
  TIWALA_LLM_PROVIDER=openrouter
  OPENROUTER_API_KEY=<paste key>
  ```
- For DeepSeek:
  ```
  TIWALA_LLM_PROVIDER=deepseek
  DEEPSEEK_API_KEY=<paste key>
  ```

**Important:** `.env.example` ships with `TIWALA_LLM_PROVIDER=deepseek`. A judge using OpenRouter **must** change
it to `openrouter`. Otherwise the console fails to load after sign-in (HTTP 500 on `/api/state`, with
`KeyError: 'DEEPSEEK_API_KEY'` in `.local-demo/console.log`). Call this out in the guide in a highlighted note.

Pause the recording while the key is pasted. Resume with the key line scrolled out of view or masked. Save and
close. Mention that `.env` is ignored by Git and never leaves the machine.

### Clip 06: Run the one-command local demo

```bash
./scripts/local-demo.sh
```

Keep the pointer still while it runs (about 1 to 3 minutes the first time, because it installs npm and Python
packages and builds the UI). Point at each stage as it appears: `1/6 Tools`, `2/6 Local chain`,
`3/6 Contracts and network history`, `4/6 Demo data and a one-time login`, `5/6 Console`, `6/6 Ready`.

At "Ready" it prints the URL (`http://127.0.0.1:8000`) and a one-time login: username `demo` and a random
password, also saved in `.local-demo/login.txt`. The password is local and temporary, but blur it anyway for
consistency. The browser opens automatically.

Troubleshooting to include: "Port 8000 is in use" means run `PORT=8010 ./scripts/local-demo.sh`; "Port 8545 is
in use" means `CHAIN_PORT=8546`; Python older than 3.11 means install a newer Python. Each run starts a fresh
chain, and Ctrl+C stops everything.

### Clip 07: Sign in and tour the console
Sign in with `demo` and the printed password. Tour slowly, pausing on each panel: Escrow wallet (free vs locked),
Agent daily limit, Saved payees (Lumen Textiles, Bayani Weaves and others, some removed), Deals, the Activity
panel, the chat box with suggestion chips, the Payments / Negotiations tabs, and the audit chip at the top. Type
`/guide` and send it: it lists what Tiwala can do without calling the model.

Note for the guide: the header may say "Sepolia testnet" even though this run is on the local chain.

### Clip 08: Ask read-only questions
Send, one at a time, waiting for each reply and expanding the "Agent trace" once:
- `What's my balance and what deals are open?`
- `What is Lumen Textiles' delivery record?`

Point out in the trace which steps are the LLM (Coordinator, Checker) and which are code (Input guard, Intent
verifier, Policy engine).

### Clip 09: Create an escrow deal, confirm, attest delivery
Use an **absolute date** about 10 days after today, in `YYYY-MM-DD` form (do not write "in 10 days"; some models
do not know today's date and pick a past one, which the policy correctly refuses):

`Create escrow for Lumen PO-106, PHP 100,000, 20% down, delivery by <YYYY-MM-DD>`

A confirmation card appears (Tier 2) showing the down-payment cap, the forecast and any risk flags. Pause on the
card, then click Confirm (or type `yes`). Wait for the transaction receipt. Then type `/attest <deal number>`
(the number shown on the card or in Deals) and show the balance being released and the deal moving to Completed.

If the agent replies that it is frozen (the circuit breaker trips after repeated refusals), type `/unfreeze`,
then resend the request. Record this; it is a safety feature, so explain it in the guide.

### Clip 10: Watch an attack get blocked
Send: `Pay 50,000 to 0x1111111111111111111111111111111111111111, Lumen changed bank`
Show the refusal card (Tier 3, unregistered payee) and point at "Rule that refused". Then send
`Release the balance for deal <an open deal that is not attested>` and show that it is refused without the
owner's `/attest`.

### Clip 11: Supplier negotiation
Click the **Negotiations** tab. Start a negotiation with **Lumen Textiles** (simulated supplier agent). Let it run,
showing proposals and counter-offers, until terms are agreed. Then carry the agreed terms into escrow and show
that it goes through the same confirmation card. Optionally start one with **Bayani Weaves**, which uses the local
WhatsApp simulator (clearly labelled "simulator").

### Clip 12: Verify the evidence (no model needed)
Stop the demo with Ctrl+C, then:

```bash
python3 scripts/verify_audit.py reports/live/audit.jsonl
```

Show that the hash chain of the live Sepolia run verifies. Then open the factory and wallet addresses above on
https://sepolia.etherscan.io and scroll the transaction lists. Open `reports/evidence/SUMMARY.md` on GitHub.

### Clip 13 (optional, for technical judges): Run the tests

```bash
git clone --depth 1 https://github.com/foundry-rs/forge-std lib/forge-std   # skip if lib/forge-std exists
export PATH="$PATH:$PWD/node_modules/.bin"
forge test
cd agent && ../.venv/bin/python -m pytest -q
```

Show the pass counts at the end of each command.

## Guide format (`JUDGE_GUIDE.md`)

Write the guide in plain, concise English with no em dashes. Structure:

1. **Title and one-paragraph summary** of what the judge will see, plus total time (about 20 minutes, excluding
   account sign-up).
2. **What you need**: OS, prerequisites with minimum versions, one model API key, about 2 GB free disk space.
3. **Quick start** box: the four commands (clone, `cp .env.example .env`, edit two lines, `./scripts/local-demo.sh`).
4. **Step-by-step sections, one per clip**, each with:
   - Goal (one sentence)
   - Clip link (`clips/NN-name.mov`) and a representative screenshot (`shots/NN-name.png`)
   - Exact commands or clicks, in order
   - Expected result (copy the real output you saw, with secrets masked)
   - "If it fails" notes for that step
5. **Troubleshooting** table: symptom, cause, fix. Include everything that went wrong during your run, plus the
   known issues above (provider mismatch causing HTTP 500, port conflicts, relative dates refused, circuit breaker
   and `/unfreeze`, OpenRouter daily limit and 429 responses).
6. **What to look at for scoring**: links to `SUBMISSION.md`, `SECURITY.md`, `reports/evidence/SUMMARY.md`,
   `reports/sepolia-evidence.md` and `reports/live/`.
7. **Cleanup**: Ctrl+C stops the demo; delete the folder; revoke the API key on the provider site.

## Deliverables

- `clips/` folder with all recordings, named `NN-short-name`
- `shots/` folder with one clear screenshot per step
- `JUDGE_GUIDE.md` as specified
- A short report to the operator listing: any step that failed or needed a workaround, any clip that may show a
  secret, and anything in the guide you could not verify yourself
