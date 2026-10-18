#!/usr/bin/env bash
# Deploy Tiwala to Sepolia and seed demo history. Run from the repo root: ./scripts/deploy-sepolia.sh
set -euo pipefail
set -a; source .env; set +a
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
