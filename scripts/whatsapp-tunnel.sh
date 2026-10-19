#!/usr/bin/env bash
# Public HTTPS address for Meta's WhatsApp webhook, without exposing the console.
#
#   internet -> tunnel (cloudflared, or ngrok) -> webhook gate 127.0.0.1:8001 -> console 127.0.0.1:8000
#
# The gate forwards only /webhooks/whatsapp. Start the console first, then run this and paste the printed
# callback URL into the Meta app (WhatsApp > Configuration > Webhook), with WHATSAPP_VERIFY_TOKEN, and
# subscribe to the "messages" field. Ctrl+C stops the tunnel and the gate.
set -euo pipefail
cd "$(dirname "$0")/.."

GATE_PORT="${GATE_PORT:-8001}"
CONSOLE="${CONSOLE:-http://127.0.0.1:8000}"
PY="$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )"
LOG="$(mktemp -t tiwala-tunnel.XXXXXX)"
pids=()
cleanup() { for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; rm -f "$LOG"; }
trap cleanup EXIT INT TERM

env_val() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/^["'\'']//; s/["'\'']$//'; }

if ! curl -s -o /dev/null "$CONSOLE/api/session"; then
  echo "The console is not running at $CONSOLE. Start it first:"
  echo "  cd agent && ../.venv/bin/uvicorn console.server:app --port 8000"
  exit 1
fi
missing=()
for k in WHATSAPP_APP_SECRET WHATSAPP_VERIFY_TOKEN; do [ -n "$(env_val "$k")" ] || missing+=("$k"); done
if [ ${#missing[@]} -gt 0 ]; then
  echo "Set ${missing[*]} in .env and restart the console; without them every webhook call is refused."
  exit 1
fi

"$PY" scripts/webhook_gate.py --port "$GATE_PORT" --upstream "$CONSOLE" &
pids+=($!)
sleep 1

url=""
if command -v cloudflared >/dev/null; then
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$GATE_PORT" >"$LOG" 2>&1 &
  pids+=($!)
  for _ in $(seq 1 30); do
    url="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
    [ -n "$url" ] && break
    sleep 1
  done
elif command -v ngrok >/dev/null; then
  ngrok http "127.0.0.1:$GATE_PORT" --log=stdout >"$LOG" 2>&1 &
  pids+=($!)
  for _ in $(seq 1 30); do
    url="$(curl -s 127.0.0.1:4040/api/tunnels 2>/dev/null | grep -oE '"public_url":"https://[^"]+' | head -1 | cut -d'"' -f4 || true)"
    [ -n "$url" ] && break
    sleep 1
  done
else
  echo "No tunnel tool found. Install one:"
  echo "  brew install cloudflared      # free, no account"
  exit 1
fi

if [ -z "$url" ]; then
  echo "The tunnel did not start. Its log:"
  tail -20 "$LOG"
  exit 1
fi

echo
echo "Callback URL for Meta:  $url/webhooks/whatsapp"
echo "Verify token:           the WHATSAPP_VERIFY_TOKEN value in .env"
echo "Only that path is reachable through the tunnel; everything else returns 404."
echo "Quick tunnel addresses change on every run: update the callback URL in Meta each time."
echo "Requests (path and status only):"
wait "${pids[0]}"
