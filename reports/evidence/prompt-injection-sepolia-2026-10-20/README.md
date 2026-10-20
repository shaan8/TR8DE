# Sepolia prompt-injection campaign

Run on 20 October 2026 against public Sepolia state pinned at block 11,952,943. It covers 300 owner-facing
prompts: 50 each for instruction override, payment redirection, privilege escalation, secret extraction,
embedded untrusted text and confirmation forgery. Qwen Coordinator/Treasury used `qwen3.7-plus`; Checker used
`qwen3.8-flash`.

The 300 results were 289 clarification/no-action responses, 10 refusals and one owner-confirmation card. There
were no model errors, inconclusive results, or calls to the transaction sender. The harness disabled contract
broadcasts and kept the agent signer out of the prompt run. It allowed public-chain reads and contract
simulations with `eth_call`. Inputs used generic supplier labels and empty synthetic plans; local chat history
was not included.

After the prompts finished, the agent wallet sent six zero-value transactions to itself, one per family. Each
transaction commits that family's Merkle root; every prompt/result row has its own inclusion proof and points to
the matching transaction hash. These are public evidence commitments, not escrow or supplier-payment
transactions. This means each of the 300 cases is tied to one of six hashes; there were not 300 chain
transactions.

| Family | Cases | Sepolia transaction |
| --- | ---: | --- |
| Instruction override | 50 | [0xa8eec4fd7a8656a8dd9b0b1e1e29df32d2b48493ed6601c503cd8683b824fbe9](https://sepolia.etherscan.io/tx/0xa8eec4fd7a8656a8dd9b0b1e1e29df32d2b48493ed6601c503cd8683b824fbe9) |
| Payment redirection | 50 | [0xc4e9b6fc7203f6dbfdb6ccdd967d6d9b6ec99a83982590e6aa4bb3d7e52d1f79](https://sepolia.etherscan.io/tx/0xc4e9b6fc7203f6dbfdb6ccdd967d6d9b6ec99a83982590e6aa4bb3d7e52d1f79) |
| Privilege escalation | 50 | [0x47c522ebc2168fa68f2f4dc701e401fcb3819cb24e8da49888260554d07e9a27](https://sepolia.etherscan.io/tx/0x47c522ebc2168fa68f2f4dc701e401fcb3819cb24e8da49888260554d07e9a27) |
| Secret extraction | 50 | [0x98374896d3a07dc9df6e63573e98b778ef7fdd8e245ecba058e3c5cb2947e976](https://sepolia.etherscan.io/tx/0x98374896d3a07dc9df6e63573e98b778ef7fdd8e245ecba058e3c5cb2947e976) |
| Embedded untrusted text | 50 | [0x27e463189470bc757c0f39976b86cf8125b0eb10102023a487b45d0334eac8d6](https://sepolia.etherscan.io/tx/0x27e463189470bc757c0f39976b86cf8125b0eb10102023a487b45d0334eac8d6) |
| Confirmation forgery | 50 | [0xd241ef79b014d3eae153d553db72efb417aaacbcd25b5e631dc2c033d1953ba9](https://sepolia.etherscan.io/tx/0xd241ef79b014d3eae153d553db72efb417aaacbcd25b5e631dc2c033d1953ba9) |

Run the verifier from the repository root after installing the agent dependencies:

```sh
python3 scripts/verify_prompt_campaign.py
```

The default run checks all prompt/result checksums and Merkle proofs, then reads the six transactions from public
Sepolia RPC and verifies their receipt, sender, recipient, zero value and committed calldata. Add `--offline` to
check the local bundle without network access. The script uses no signer or API key.

The campaign ran from the working tree based on `8afe49d6995c4fba512a9b0665816723bdb30429`. That exact agent
source tree was committed as `78360b033a0e4d7526d9b16bb0620de7753c8bf9`; its per-file digests match
`agent-source-files.sha256` and the aggregate SHA-256 in `summary.json`. The bundle records both revisions.

Scope limit: these were owner-facing prompts through the agent pipeline, not live WhatsApp, Telegram or supplier
API conversations. No attack attempt was allowed to broadcast. The campaign tests model and policy handling
against pinned public state; it does not show funds moving or prove the broadcast path against the same attacks.

The v1 leaf encoding is retained in the verifier so proofs match the public roots. It uses the 31-byte suffix of
each prompt and result Keccak digest, followed by a Keccak hash of the encoded leaf. A future campaign should use
the full 32-byte digests under a new versioned commitment marker.
