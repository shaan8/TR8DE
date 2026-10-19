# Receiving WhatsApp replies on a laptop

Sending to WhatsApp is an outbound call and works from anywhere. Receiving does not: Meta delivers each supplier
message to a public HTTPS webhook. (Telegram has no such limit; see [telegram.md](telegram.md).) The console runs on
localhost, so `scripts/whatsapp-tunnel.sh` gives it a public address without exposing the console itself:

```
Meta -> https://<random>.trycloudflare.com -> webhook gate 127.0.0.1:8001 -> console 127.0.0.1:8000
```

The gate (`scripts/webhook_gate.py`) forwards only `GET` and `POST /webhooks/whatsapp`, passes only the
`Content-Type` and `X-Hub-Signature-256` headers (no cookies), caps bodies at 1 MB, and returns 404 for every other
path. The login page, chat, negotiations and supplier API are not reachable through the tunnel at all. The console
still checks the verify token and Meta's HMAC signature on every call.

## Setup

Live mode only: the local demo blanks every WhatsApp setting so it can never message anyone.

0. `.env`: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` (Meta app > WhatsApp > API setup),
   `WHATSAPP_TEMPLATE_NAME=hello_world` (Meta's pre-approved template, used for the first message), and
   `WHATSAPP_LIVE_SEND=1`. `WHATSAPP_ALLOWED_RECIPIENTS` is optional: if set, only those numbers can be messaged.
1. In `.env`: `WHATSAPP_APP_SECRET` (Meta app > App settings > Basic > App secret) and `WHATSAPP_VERIFY_TOKEN`
   (any string you choose). Restart the console.
2. `brew install cloudflared` (free, no account). If it is missing, the script uses ngrok when installed.
3. With the console running: `./scripts/whatsapp-tunnel.sh`. It prints the callback URL.
4. Meta app > WhatsApp > Configuration > Webhook: paste the callback URL and the verify token, then subscribe to the
   `messages` field.
5. Link the supplier: Negotiations tab, pick the payee, type their number and press "Link WhatsApp", or type
   `/whatsapp Lumen Textiles +63 917 123 4567` in the Payments chat. Then start a negotiation with "Supplier's
   person on WhatsApp or Telegram". The first message is the `hello_world` template; the offer follows as soon as
   they reply (WhatsApp's 24-hour rule).
6. Send a message from the supplier's phone. The gate prints one line per request (path and status only).

## Limits

- Quick tunnel addresses change every run, so update the callback URL in Meta after each restart. An ngrok
  account gives one fixed domain.
- Free-form replies are allowed for 24 hours after the supplier's last message. Outside that window the first
  message must be an approved template (`WHATSAPP_TEMPLATE_NAME`; `hello_world` works for testing).
- The tunnel is only up while the script runs and the laptop is awake. A production deployment would host the
  webhook on a server instead.
