# Telegram supplier channel

Live mode only: the local demo blanks every Telegram setting so it can never message anyone.

Telegram is a second chat channel for the supplier's person, next to WhatsApp. It runs through the same Gateway, so the same rules apply: only bound chats are heard, every message is deduplicated, STOP opts out, "talk to a person" escalates to the owner, and only an exact `ACCEPT <code>` counts as acceptance. Free text is read as a candidate counteroffer only.

## No webhook needed

WhatsApp Cloud API pushes messages to a public HTTPS webhook, so it cannot reach a laptop. Telegram also offers `getUpdates`: the console makes an outbound HTTPS request that Telegram holds open for up to 25 s and answers as soon as a message arrives (long polling). Replies are a plain `sendMessage` call. Both directions work from localhost behind NAT, and nothing is exposed to the internet.

Telegram has no 24-hour window and no templates: a bot may message any chat that has pressed Start, until that person blocks the bot.

## Setup

1. In Telegram, message @BotFather, send `/newbot`, and copy the token.
2. In `.env`: `TELEGRAM_BOT_TOKEN=<token>` and `TELEGRAM_LIVE_SEND=1`.
3. Restart the console. It starts polling on startup (the Negotiate page shows "Telegram bot listening").
4. Make a one-time invite for a saved payee: in the console's Negotiations tab pick the supplier and press
   "Invite on Telegram", or type `/invite Lumen Textiles` in the Payments chat (no model key needed). From a shell:
   `.venv/bin/python -m tiwala_agent.telegram invite "Lumen Textiles"`.
5. The supplier opens the link and presses Start. Their chat is bound to that payee, and they get a confirmation.
6. Open a negotiation with "Supplier's person on WhatsApp or Telegram". Offers go to their chat, and replies come back into the negotiation.

## Safety

- Invite codes are single use, expire after 7 days, and are stored only as SHA-256 hashes.
- Chats that were never bound, group chats, channels, edits and media are ignored.
- The bot token is never logged, and it is masked in error messages.
- If a webhook is already set on the bot, `getUpdates` returns 409. Remove the webhook (`deleteWebhook`) or use a fresh bot.
- Only one process may poll a bot token. Two consoles with the same token conflict.
