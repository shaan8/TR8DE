You are recording short screen videos for the README of TR8DE, an AI escrow wallet agent
(github.com/shaan8/TR8DE). Use computer use on my Mac. The project is at
~/Downloads/tiwala_SEPOLIA. Read README.md first: every clip below matches one of its sections.

## Hard rules

1. Never show a secret on screen: no `.env` contents, API keys, bot tokens, access tokens, private keys,
   passwords or seed phrases. Never open `.env` in an editor or `cat` it. If a secret appears by accident, stop,
   delete that recording and start the clip again.
2. Record everything except section 4 against the LOCAL DEMO only (a throwaway chain on this Mac). Do not run
   `./scripts/live.sh`, do not send Sepolia transactions, do not fund any wallet, do not use a faucet.
3. Never send a real WhatsApp or Telegram message and never message a person. The local demo disables both;
   use its built-in WhatsApp simulator.
4. Do not create accounts, sign in to anything, accept terms or cookie banners, or enter payment details. For the
   API-key clips, record only public pages up to the sign-in screen and stop there.
5. Do not edit, commit or push anything in the repository. The only file you may change is the demo data file
   named in clip 2c, which lives in the git-ignored `.local-demo/` folder.
6. If anything asks for approval, a password or a decision, stop and ask me.

## Format

- MP4 (H.264), 1440x900 browser window (or the terminal at a similar size), 10 to 40 seconds each, under 10 MB
  so GitHub accepts it as a README attachment. Also export each one as a GIF under 5 MB (GIFs autoplay in a
  README, MP4s show a player).
- No sound. Hide the Dock, notifications and bookmarks bar. Use a large terminal font (16 pt or more).
- Pause about 1 second after each action so a viewer can follow. Type at a readable speed.
- Name files `<section>-<slug>.mp4`, for example `0.2-local-demo.mp4`, and save them to
  ~/Desktop/tr8de-videos/.

## Setup (do not record)

```bash
cd ~/Downloads/tiwala_SEPOLIA
PORT=8010 CHAIN_PORT=8546 NO_BROWSER=1 ./scripts/local-demo.sh
```

(Port 8000 is my live console: never touch it.)

When it prints "Ready", open http://127.0.0.1:8010 in the browser and sign in with the username and one-time
password it printed. That password is a throwaway for this local demo only; still, do not keep it on screen in
any final clip (crop or start recording after sign-in). Leave the script running in its own terminal tab.

## Shot list

### Header: hero (README top)
- `0-hero`: the Agent workspace with the treasury panel visible. Click through Agent workspace, Payments,
  Negotiations, Suppliers in the left sidebar. 10 to 15 s.

### What you can do
- `1a-wallet-planning`: type and send each of these, waiting for the answer:
  "What's my balance and what deals are open?", "What is Lumen Textiles' delivery record?",
  "Can I afford a PHP 80,000 PO on 2026-10-30?" (one clip, or three short ones).
- `1b-card-approval`: send "Create escrow for Lumen PO-104, PHP 120,000, 20% down, delivery by 2026-10-30".
  Show the approval card, open "View policy, liquidity & independent checks", then press "Review & approve" and
  show the receipt and the treasury panel updating.
- `1c-agent-acts-alone`: the demo seeds planned purchases that make every new deal raise a forecast flag, which
  sends it to a card. Before this clip only, stop the console's planned purchases by running (not recorded):

  ```bash
  cd ~/Downloads/tiwala_SEPOLIA && python3 -c "import json; json.dump({'buffer':0,'inflows':[],'planned':[]}, open('.local-demo/data/plans.json','w'))"
  ```

  Then send "Create escrow for Lumen PO-107, PHP 20,000, 20% down, delivery by 2026-10-30". Show that no card
  appears, the deal is created and the deposit released, and it shows in the Activity tab as Autonomous.
  If a card still appears, stop and tell me what the card's "Policy" line says.
- `1d-release-and-attest`: type `/attest <deal number from 1b>`, then press "Run monitor". Show the owner-key
  receipt, the balance release, and both entries in the Activity tab.
- `1e-negotiation-agent`: Negotiations tab, keep the default form (Lumen, supplier agent), press
  "Start negotiating". Record the offers going back and forth until "Agreed", then "Recheck and prepare escrow"
  and "Yes, create the escrow". The model is slow; cut the waiting so the clip stays under 40 s.
- `1f-negotiation-whatsapp-sim`: start a negotiation with Bayani Weaves and "Supplier's person on WhatsApp or
  Telegram". In the WhatsApp simulator panel, type a counteroffer like "We can do 400 at 120 each", then
  `ACCEPT <code>` using the code of the open offer. Show each reply arriving.
- `1g-supplier-console`: the supplier's own page. On the Negotiations page, with a negotiation selected, press
  "Open supplier's console ↗" (local demo only). Show the mandate form and the buyer's offer, press
  "Pause agent and take over", then "Accept".
- `1h-save-supplier`: send "Save a new supplier, Kalinaw Crafts, payout 0xa0Ee7A142d267C1f36714E4a8F75612F20a79720"
  (a public Anvil test address). Show every check on the card, type the last 4 characters (`9720`) and press
  "Sign with owner key". Then send "Save a new supplier, Kalinaw Trading, payout 0xa0ee7a142d267c1f36714e4a8f75612f20a79720" with one
  middle character changed (keep it all lowercase and keep the first and last 4 characters) to show the
  lookalike refusal.
- `1i-commands`: type `/guide`, then `/limits`, then `/verify`. One clip.
- `1j-suppliers-page`: the Suppliers page, open "Connect chat" on one supplier (do not press Invite or Link).

### 0. How to deploy
- `0.1-requirements` (terminal): `git --version`, `node -v`, `python3 --version`.
- `0.2-local-demo` (terminal, then browser): in a NEW terminal and an empty folder, run
  `git clone https://github.com/shaan8/TR8DE.git && cd TR8DE && NO_BROWSER=1 PORT=8020 CHAIN_PORT=8547 ./scripts/local-demo.sh`
  (other ports, since the setup demo is still running). Cut the install wait. Stop recording before the line that
  prints the password, then show the browser on http://127.0.0.1:8020 after sign-in. Ctrl+C it afterwards.
- `0.3-keys-*` (browser, public pages only, stop at any sign-in screen):
  `0.3-keys-qwen` Alibaba Cloud Model Studio product page to the console sign-in;
  `0.3-keys-deepseek` platform.deepseek.com; `0.3-keys-openrouter` openrouter.ai/keys;
  `0.3-keys-anthropic` console.anthropic.com; `0.3-keys-faucet` the Google Cloud Sepolia faucet page (do not
  request funds); `0.3-keys-alchemy` dashboard.alchemy.com sign-in page; `0.3-keys-telegram` the @BotFather page
  at t.me/BotFather; `0.3-keys-meta` developers.facebook.com/apps; `0.3-keys-ngrok` ngrok.com/download, then in a
  terminal `brew info ngrok` (do not install, do not run `ngrok config add-authtoken`).
  Also `0.3-setup-qwen` (terminal): run `python3 scripts/setup_qwen.py --help` only.
- `0.4-live`: do not record. I will record this one myself because it needs a funded key.
- `0.5-entry-points` (browser + terminal): open http://127.0.0.1:8010/?fixture=approval and switch two states in
  the "Screen state" picker; then in a terminal run `cd agent && ../.venv/bin/python -m tiwala_agent.cli --help`.
- `0.6-demo-vs-live`: skip; the README table covers it.
- `0.7-tests` (terminal, from the repository root, cut the waiting):
  `PATH=$HOME/.foundry/bin:$PATH forge test`, then
  `cd agent && PATH=$HOME/.foundry/bin:$PATH ../.venv/bin/python -m pytest -q`, then
  `cd ../ui && UI_PORT=8011 npx playwright test`. Show each final "passed" line.

### 4. Execution evidence (public, read-only)
- `4a-etherscan`: open each transaction link in README section 4 on sepolia.etherscan.io and show "Success" and
  the From/To lines; include the reverted backstop transaction showing "Fail". Do not connect a wallet.
- `4b-verify-audit` (terminal): `python3 scripts/verify_audit.py reports/live/audit.jsonl`.

## When done

Stop the demo with Ctrl+C. Reply with a table: file name, README section it belongs to, length, size, and one
line on what it shows. List any clip you skipped and why.
