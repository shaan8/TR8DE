#!/usr/bin/env bash
# Tiwala local demo: a private Ethereum chain on this machine, the real contracts, seeded suppliers and the console.
# No real money, no testnet faucet, no WhatsApp. Needs: git, Node 18+, Python 3.11+.
#
#   ./scripts/local-demo.sh            # then open http://127.0.0.1:8000 (opens automatically)
#
# Optional: a model key in .env (DASHSCOPE_API_KEY for Qwen Cloud, DEEPSEEK_API_KEY, OPENROUTER_API_KEY or
# ANTHROPIC_API_KEY) for the chat assistant; the first provider with a key is used.
# Without one, negotiations still run (rule-based buyer, scripted supplier) and the chat says the model is off.
# Ctrl+C stops everything. Each run starts from a fresh chain.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO="$ROOT/.local-demo"
PORT="${PORT:-8000}"
CHAIN_PORT="${CHAIN_PORT:-8545}"
FORGE_STD_COMMIT="b013eff2ac4fce26f34d789e6f5c49021c5ee817"
# Public Anvil development keys: they only hold value on this local chain.
KEY_DEPLOYER="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
KEY_OWNER="0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
KEY_AGENT="0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed. $2"; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

cd "$ROOT"
need git "Install it from https://git-scm.com"
need node "Install Node 18+ from https://nodejs.org"
need npm "It comes with Node: https://nodejs.org"
need python3 "Install Python 3.11+ from https://www.python.org"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is needed (found $(python3 -V))."
port_busy "$PORT" && fail "Port $PORT is in use (another Tiwala console?). Stop it, or run PORT=8010 $0"
port_busy "$CHAIN_PORT" && fail "Port $CHAIN_PORT is in use. Stop that process, or run CHAIN_PORT=8546 $0"

say "1/6 Tools"
if [ ! -d node_modules/@openzeppelin ]; then npm ci --no-audit --no-fund --loglevel=error; fi
export PATH="$PATH:$ROOT/node_modules/.bin"  # a system Foundry install wins; the npm one is the fallback
need forge "Install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup"
need anvil "Install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup"
if [ ! -d lib/forge-std/src ]; then
  git clone -q https://github.com/foundry-rs/forge-std lib/forge-std
  git -C lib/forge-std checkout -q "$FORGE_STD_COMMIT"
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if [ ! -f .venv/.req ] || ! cat agent/requirements.txt agent/requirements.lock | cmp -s - .venv/.req; then
  .venv/bin/pip install -q --disable-pip-version-check -r agent/requirements.txt -c agent/requirements.lock \
    && cat agent/requirements.txt agent/requirements.lock > .venv/.req
fi
if [ ! -f ui/dist/index.html ] || [ -n "$(find ui/src ui/index.html -newer ui/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd ui && { [ -d node_modules ] || npm ci --no-audit --no-fund --loglevel=error; } && npm run build --silent >/dev/null)
fi

rm -rf "$DEMO" && mkdir -p "$DEMO"
cleanup() {
  local status=$?
  [ -n "${CONSOLE_PID:-}" ] && kill "$CONSOLE_PID" 2>/dev/null || true
  [ -n "${CHAIN_PID:-}" ] && kill "$CHAIN_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo; echo "Stopped. Chain and demo data were temporary."
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

say "2/6 Local chain"
anvil --port "$CHAIN_PORT" --silent >"$DEMO/anvil.log" 2>&1 &
CHAIN_PID=$!
RPC="http://127.0.0.1:$CHAIN_PORT"
for _ in $(seq 1 50); do port_busy "$CHAIN_PORT" && break; sleep 0.2; done
port_busy "$CHAIN_PORT" || fail "The local chain did not start; see $DEMO/anvil.log"

say "3/6 Contracts and network history (about 30 s)"
export PRIVATE_KEY="$KEY_DEPLOYER" OWNER_PRIVATE_KEY="$KEY_OWNER" AGENT_PRIVATE_KEY="$KEY_AGENT" \
       ACCOUNT_SALT="0x$(printf '11%.0s' $(seq 1 32))" DEMO_GRACE=600 LATE_WINDOW=120
forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast >"$DEMO/deploy.log" 2>&1 \
  || fail "Deploying the contracts failed; see $DEMO/deploy.log"
cast rpc evm_increaseTime 200 --rpc-url "$RPC" >/dev/null && cast rpc evm_mine --rpc-url "$RPC" >/dev/null
forge script script/Finish.s.sol --rpc-url "$RPC" --broadcast >>"$DEMO/deploy.log" 2>&1 \
  || fail "Seeding the network history failed; see $DEMO/deploy.log"

say "4/6 Demo data and a one-time login"
PASSWORD="$(cd agent && ../.venv/bin/python -m console.local_demo seed "$ROOT/deployments/31337.json" "$DEMO")"

say "5/6 Console"
MODEL_KEY=0
for k in DEEPSEEK_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY DASHSCOPE_API_KEY; do
  if [ -n "${!k:-}" ] || grep -Eq "^$k=.+" .env 2>/dev/null; then MODEL_KEY=1; fi
done
set -a; . "$DEMO/env"; set +a
export RPC_URL="$RPC" TIWALA_DEPLOYMENT="$ROOT/deployments/31337.json" TIWALA_DATA="$DEMO/data" \
       TIWALA_AUDIT="$DEMO/audit.jsonl" TIWALA_SUPPLIER_CONSOLE_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
# Never touch live messaging from the demo, whatever .env says.
export WHATSAPP_LIVE_SEND=0 WHATSAPP_ACCESS_TOKEN="" WHATSAPP_PHONE_NUMBER_ID="" WHATSAPP_APP_SECRET="" \
       WHATSAPP_VERIFY_TOKEN="" WHATSAPP_ALLOWED_RECIPIENTS="" \
       TELEGRAM_BOT_TOKEN="" TELEGRAM_LIVE_SEND=0 TELEGRAM_POLL=0
if [ "$MODEL_KEY" = 0 ]; then export TIWALA_NEGOTIATOR=rules TIWALA_SUPPLIER_AGENT=scripted TIWALA_CHECKER=rules; fi
(cd agent && exec ../.venv/bin/uvicorn console.server:app --host 127.0.0.1 --port "$PORT" --log-level warning) \
  >"$DEMO/console.log" 2>&1 &
CONSOLE_PID=$!
for _ in $(seq 1 100); do curl -fs "http://127.0.0.1:$PORT/api/session" >/dev/null 2>&1 && break; sleep 0.3; done
curl -fs "http://127.0.0.1:$PORT/api/session" >/dev/null 2>&1 || fail "The console did not start; see $DEMO/console.log"
LUMEN="$(.venv/bin/python -c "import json;print(json.load(open('deployments/31337.json'))['suppliers']['Lumen Textiles'])")"
LUMEN_TOKEN="$(cd agent && ../.venv/bin/python -c "from console.negotiation_api import supplier_token; print(supplier_token('$LUMEN'))")"

say "6/6 Ready"
cat <<EOF

  Open      http://127.0.0.1:$PORT
  Sign in   username demo, password $PASSWORD   (also in .local-demo/login.txt)

  Try:
  - Negotiations: start one with Lumen (simulated supplier agent) or Bayani (WhatsApp simulator). When both
    sides agree, press "Recheck and prepare escrow", then reply "yes" in Payments to lock it on the chain.
  - Payments: type "/attest <deal>" to confirm delivery and watch the balance release and Lumen's record change.
    With a model key you can also ask in plain words, e.g. "Create escrow for Lumen PO-104, PHP 120,000, 20% down".
  - Your own supplier agent: in another terminal,
      TIWALA_SUPPLIER_TOKEN=$LUMEN_TOKEN python3 scripts/supplier_agent_example.py \\
        --url http://127.0.0.1:$PORT --supplier $LUMEN --min-price 110 --max-qty 450 --min-deposit 15
    then start a Lumen negotiation with "Supplier's own system (API)".
EOF
if [ "$MODEL_KEY" = 0 ]; then
  echo "  Note: no model key found in .env. The chat assistant is off, negotiations use rules and a scripted supplier,"
  echo "  and payments use a labelled rules-only Checker (intent, policy and contract checks still apply). Add"
  echo "  DASHSCOPE_API_KEY (Qwen Cloud), DEEPSEEK_API_KEY, OPENROUTER_API_KEY or ANTHROPIC_API_KEY to .env and rerun."
fi
echo
echo "  Ctrl+C to stop."
if [ -z "${NO_BROWSER:-}" ]; then (open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null || true) & fi
wait "$CONSOLE_PID"
