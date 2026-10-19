#!/usr/bin/env bash
# Deploy TR8DE to Sepolia and seed demo history. Run from the repo root: ./scripts/deploy-sepolia.sh
set -euo pipefail
# Read only the keys this script needs, without running .env as shell code (values may contain "$" or spaces).
# Values already in the environment win, as with the console.
eval "$(python3 - <<'PY'
import os, shlex
keys = ("SEPOLIA_RPC_URL", "PRIVATE_KEY", "OWNER_PRIVATE_KEY", "AGENT_PRIVATE_KEY", "ACCOUNT_SALT", "ETHERSCAN_API_KEY",
        "LATE_WINDOW", "DEMO_GRACE", "BUYER_FUND_WEI", "PAYEE_DELAY")
vals = {}
if os.path.exists(".env"):
    for line in open(".env").read().splitlines():
        line = "" if line.lstrip().startswith("#") else line.split(" #", 1)[0].strip()
        k, sep, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if sep and k.strip() in keys:
            vals[k.strip()] = v
for k, v in vals.items():
    if not os.environ.get(k):
        print(f"export {k}={shlex.quote(v)}")
PY
)"
: "${SEPOLIA_RPC_URL:?}" "${PRIVATE_KEY:?}" "${OWNER_PRIVATE_KEY:?}" "${AGENT_PRIVATE_KEY:?}" "${ACCOUNT_SALT:?}"

echo "Deployer: $(cast wallet address --private-key "$PRIVATE_KEY")"
echo "Balance:  $(cast balance --ether "$(cast wallet address --private-key "$PRIVATE_KEY")" --rpc-url "$SEPOLIA_RPC_URL") ETH"

VERIFY=()
if [[ -n "${ETHERSCAN_API_KEY:-}" ]]; then VERIFY=(--verify --etherscan-api-key "$ETHERSCAN_API_KEY"); fi

forge script script/Deploy.s.sol --rpc-url "$SEPOLIA_RPC_URL" --broadcast --slow --skip-simulation --gas-estimate-multiplier 130 ${VERIFY[@]+"${VERIFY[@]}"}

DEADLINE=$(python3 -c "import json;print(json.load(open('deployments/11155111.json'))['lateDeadline'])")
while :; do
  NOW=$(cast block latest --field timestamp --rpc-url "$SEPOLIA_RPC_URL")
  (( NOW > DEADLINE )) && break
  echo "Waiting $((DEADLINE - NOW + 15))s for the late deals' deadline..."; sleep $((DEADLINE - NOW + 15))
done
forge script script/Finish.s.sol --rpc-url "$SEPOLIA_RPC_URL" --broadcast --slow --skip-simulation --gas-estimate-multiplier 130

echo "Done. Addresses: deployments/11155111.json; tx hashes: broadcast/*/11155111/run-latest.json"
