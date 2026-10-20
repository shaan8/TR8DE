#!/usr/bin/env bash
# TR8DE live on Sepolia: your own contracts on the public Ethereum test network, real transactions you can show
# on Etherscan, then the console. Needs git, Node 18+, Python 3.11+, and about 0.02 Sepolia test ETH
# (free from a faucet; the script makes the key and tells you which address to fund).
#
#   1. Put a model key in .env (OPENROUTER_API_KEY has free models), then run ./scripts/live.sh
#   2. It creates a deployer key, prints its address and stops: send it 0.02 Sepolia ETH from a faucet, rerun
#
# The script creates the owner and agent keys if .env has none, deploys the token, factory and wallets, seeds
# supplier history, and starts the console. Expect about 50 minutes on the first run: Sepolia confirms one block every
# 12 seconds, the deploy sends about 110 transactions, and two seeded "late" deals must pass their deadline.
# A second run reuses your deployment. Test tokens only: never put a key that holds real funds in .env.
set -euo pipefail
export TIWALA_AUTH_DISABLED=0  # setup always starts with authentication enabled

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
FORGE_STD_COMMIT="b013eff2ac4fce26f34d789e6f5c49021c5ee817"
DEP="deployments/11155111.json"

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed. $2"; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
envval() {  # value of KEY in .env: inline "  # comment" and surrounding quotes removed
  grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -E "s/[[:space:]]+#.*$//; s/[[:space:]]+$//; s/^['\"](.*)['\"]$/\1/" || true
}
setenv() {  # add or replace KEY=VALUE in .env without echoing the value
  .venv/bin/python - "$1" "$2" <<'PY'
import os, sys
k, v = sys.argv[1], sys.argv[2]
p = ".env"
lines = open(p).read().splitlines() if os.path.exists(p) else []
lines = [l for l in lines if l.split("=", 1)[0].strip() != k] + [f"{k}={v}"]
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
}

cd "$ROOT"
need git "Install it from https://git-scm.com"
need node "Install Node 18+ from https://nodejs.org"
need npm "It comes with Node: https://nodejs.org"
need python3 "Install Python 3.11+ from https://www.python.org"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is needed (found $(python3 -V))."
port_busy "$PORT" && fail "Port $PORT is in use (another TR8DE console?). Stop it, or run PORT=8010 $0"

say "1/6 Tools"
if [ ! -d node_modules/@openzeppelin ]; then npm ci --no-audit --no-fund --loglevel=error; fi
export PATH="$PATH:$ROOT/node_modules/.bin"
need forge "Install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup"
need cast "Install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup"
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

say "2/6 Keys and network"
[ -f .env ] || touch .env
chmod 600 .env
RPC="${SEPOLIA_RPC_URL:-$(envval SEPOLIA_RPC_URL)}"
RPC="${RPC:-https://ethereum-sepolia-rpc.publicnode.com}"
PK="$(envval PRIVATE_KEY)"
if [ -z "$PK" ]; then  # no deployer key yet: make one, so the judge only has to fund an address
  setenv PRIVATE_KEY "$(.venv/bin/python -c 'from eth_account import Account; k = Account.create().key.hex(); print(k if k.startswith("0x") else "0x" + k)')"
  PK="$(envval PRIVATE_KEY)"
  echo "  Created a deployer key (PRIVATE_KEY in .env, owner-only file). It holds test ETH only."
fi
CHAIN="$(cast chain-id --rpc-url "$RPC" 2>/dev/null)" || fail "Cannot reach the Sepolia RPC at $RPC. Set SEPOLIA_RPC_URL in .env."
[ "$CHAIN" = "11155111" ] || fail "$RPC is chain $CHAIN, not Sepolia (11155111)."
for k in OWNER_PRIVATE_KEY AGENT_PRIVATE_KEY; do
  if [ -z "$(envval $k)" ]; then
    setenv "$k" "$(.venv/bin/python -c 'from eth_account import Account; k = Account.create().key.hex(); print(k if k.startswith("0x") else "0x" + k)')"
    echo "  Created $k in .env (owner-only file)."
  fi
done
[ -n "$(envval ACCOUNT_SALT)" ] || setenv ACCOUNT_SALT "0x$(openssl rand -hex 32)"
DEPLOYER="$(cast wallet address --private-key "$PK")"
OWNER="$(cast wallet address --private-key "$(envval OWNER_PRIVATE_KEY)")"
MODEL_KEY=0
for k in DASHSCOPE_API_KEY DEEPSEEK_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY; do [ -n "$(envval $k)" ] && MODEL_KEY=1; done
if [ "$MODEL_KEY" = 0 ]; then
  echo "  No model key in .env. Live mode refuses every payment without one: the independent Checker fails closed."
  echo "  The chat is off too. Add DASHSCOPE_API_KEY (Qwen Cloud, the default) to .env, or DEEPSEEK_API_KEY,"
  echo "  OPENROUTER_API_KEY or ANTHROPIC_API_KEY. The deployment and console still work without one."
fi

REUSE=0  # only a deployment this script finished, for these keys
if [ -f "$DEP" ] && [ -f .live-deployed ] && [ "$(cat .live-deployed)" = "$(echo "$OWNER" | tr A-Z a-z)" ]; then
  REUSE=1
fi

if [ "$REUSE" = 0 ]; then
  say "3/6 Deploying to Sepolia (about 50 minutes; leave it running)"
  BAL_WEI="$(cast balance "$DEPLOYER" --rpc-url "$RPC")"
  .venv/bin/python -c "import sys; sys.exit(int('$BAL_WEI') < 2 * 10**16)" || fail "Fund the deployer, then rerun ./scripts/live.sh.

  Address   $DEPLOYER
  Balance   $(cast from-wei "$BAL_WEI") Sepolia ETH; it needs 0.02 (test ETH, free, no real value)
  Faucets   https://cloud.google.com/application/web3/faucet/ethereum/sepolia   (Google account)
            https://sepolia-faucet.pk910.de   (no account: your browser mines for a few minutes)
            https://www.alchemy.com/faucets/ethereum-sepolia   (needs a little mainnet ETH)"
  if [ -f "$DEP" ] && [ ! -f deployments/11155111.reference.json ]; then cp "$DEP" deployments/11155111.reference.json; fi
  # The seeded late deals need a deadline after all ~110 transactions land (12 s blocks): 45 minutes, as in the
  # original deployment.
  # Gas on Sepolia costs a few wei, so 0.002 ETH per seeded buyer (0.004 for owner and agent) is plenty.
  export SEPOLIA_RPC_URL="$RPC" LATE_WINDOW="${LATE_WINDOW:-2700}" BUYER_FUND_WEI="${BUYER_FUND_WEI:-2000000000000000}" \
         PAYEE_DELAY="${PAYEE_DELAY:-600}"  # new payees wait 10 minutes before they can be paid (24 h in production)
  restore() { [ -f deployments/11155111.reference.json ] && cp deployments/11155111.reference.json "$DEP" || rm -f "$DEP"; }
  ./scripts/deploy-sepolia.sh 2>&1 | tee .live-deploy.log | grep -E "^(Deployer|Balance|Waiting|Done)" \
    || { restore; fail "The deployment failed; see .live-deploy.log. Rerun to start a fresh deployment."; }
  grep -q "^Done" .live-deploy.log || { restore; fail "The deployment did not finish; see .live-deploy.log"; }
  echo "$OWNER" | tr A-Z a-z > .live-deployed
  rm -rf agent/data/suppliers.json agent/data/negotiation
else
  say "3/6 Reusing your Sepolia deployment ($DEP)"
fi

say "4/6 Wallet data"
if [ ! -f agent/data/suppliers.json ]; then
  (cd agent && ../.venv/bin/python -m tiwala_agent.setup_data "../$DEP" data >/dev/null \
    && ../.venv/bin/python -m console.local_demo suppliers "../$DEP" data)  # simulated supplier side, labelled
fi

say "5/6 Owner login"
if [ -z "$(envval TIWALA_ADMIN_PASS_HASH)" ]; then
  echo "  Your console username is ${TIWALA_LOGIN_USER:-owner}. Password input is hidden."
  echo "  Choose a console password (15–256 characters; use a unique passphrase)."
  (cd agent && ../.venv/bin/python -m console.auth set-password "${TIWALA_LOGIN_USER:-owner}") || fail "No password was set."
fi

say "6/6 Console"
export RPC_URL="$RPC" TIWALA_DEPLOYMENT="$ROOT/$DEP"
(cd agent && exec ../.venv/bin/uvicorn console.server:app --no-proxy-headers --host 127.0.0.1 --port "$PORT" --log-level warning) \
  >.live-console.log 2>&1 &
CONSOLE_PID=$!
trap 'kill $CONSOLE_PID 2>/dev/null || true; echo; echo "Stopped. Your Sepolia contracts stay deployed."' EXIT
trap 'exit 130' INT TERM
for _ in $(seq 1 100); do curl -fs "http://127.0.0.1:$PORT/api/session" >/dev/null 2>&1 && break; sleep 0.3; done
curl -fs "http://127.0.0.1:$PORT/api/session" >/dev/null 2>&1 || fail "The console did not start; see .live-console.log"
WALLET="$(.venv/bin/python -c "import json;print(json.load(open('$DEP'))['demoWallet'])")"
cat <<EOF

  Open      http://127.0.0.1:$PORT   (sign in as $(envval TIWALA_ADMIN_USER), your password)
  Wallet    https://sepolia.etherscan.io/address/$WALLET
  Every payment, attestation and refund is a real Sepolia transaction; the console links each one to Etherscan.
  Ctrl+C to stop.
EOF
if [ -z "${NO_BROWSER:-}" ]; then (open "http://127.0.0.1:$PORT" 2>/dev/null || xdg-open "http://127.0.0.1:$PORT" 2>/dev/null || true) & fi
wait "$CONSOLE_PID"
