#!/usr/bin/env python3
"""Verify TR8DE's 20 October 2026 Sepolia prompt-campaign bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from web3 import Web3


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def result_material(record: dict[str, Any]) -> str:
    return json.dumps(
        {
            "outcome": record["outcome"],
            "reply": record.get("reply", ""),
            "events": record.get("events", []),
            "attempts": record.get("broadcast_attempts", []),
            "simulations": record.get("simulations", []),
            "errors": record.get("model_errors", {}),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def verify_leaf(record: dict[str, Any], proof: dict[str, Any], root: str) -> None:
    material = result_material(record)
    prompt_sha256 = hashlib.sha256(record["prompt"].encode()).hexdigest()
    result_sha256 = hashlib.sha256(material.encode()).hexdigest()
    assert record["prompt_sha256"] == prompt_sha256, f"prompt checksum mismatch: {record['id']}"
    assert record["result_sha256"] == result_sha256, f"result checksum mismatch: {record['id']}"

    # Reproduce the campaign's v1 byte encoding exactly so the public roots verify.
    # These [2:] slices retain 31-byte suffixes because HexBytes.hex() has no 0x prefix.
    encoded = (
        Web3.keccak(text=record["id"]).hex()
        + Web3.keccak(text=record["prompt"]).hex()[2:]
        + Web3.keccak(text=material).hex()[2:]
    )
    node = Web3.keccak(bytes.fromhex(encoded))
    assert "0x" + node.hex() == proof["leaf"], f"leaf mismatch: {record['id']}"

    for step in proof["proof"]:
        sibling = bytes.fromhex(step["hash"][2:])
        node = Web3.keccak(node + sibling) if step["side"] == "right" else Web3.keccak(sibling + node)
    assert node.hex() == root[2:], f"Merkle proof mismatch: {record['id']}"


def verify_chain(anchors: dict[str, Any], rpc_url: str) -> None:
    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    assert web3.eth.chain_id == 11155111, "RPC is not Sepolia"
    pinned_block = web3.eth.get_block(anchors["pinned_block"])
    assert pinned_block["hash"].hex() == anchors["pinned_block_hash"]
    family_order = [anchor["family"] for anchor in anchors["anchors"]]

    for index, anchor in enumerate(anchors["anchors"]):
        tx_hash = "0x" + anchor["transaction_hash"]
        tx = web3.eth.get_transaction(tx_hash)
        receipt = web3.eth.get_transaction_receipt(tx_hash)
        assert receipt["status"] == 1, f"failed transaction: {tx_hash}"
        assert tx["value"] == anchor["value_wei"] == 0, f"nonzero value: {tx_hash}"
        assert tx["from"].lower() == tx["to"].lower(), f"not a self-send: {tx_hash}"
        assert receipt["blockNumber"] == anchor["block"], f"block mismatch: {tx_hash}"
        assert receipt["gasUsed"] == anchor["gas_used"], f"gas mismatch: {tx_hash}"
        assert receipt["effectiveGasPrice"] * receipt["gasUsed"] == anchor["gas_cost_wei"]
        assert bytes(tx["input"]) == bytes.fromhex(anchor["calldata"][2:]), f"calldata mismatch: {tx_hash}"

        data = bytes(tx["input"])
        assert data[:16] == b"TR8DE-REDTEAM-v1", f"commit marker mismatch: {tx_hash}"
        assert data[16] == index and anchor["family"] == family_order[index]
        assert int.from_bytes(data[17:19], "big") == anchor["count"] == 50
        assert data[19:51] == bytes.fromhex(anchor["merkle_root"][2:])
        assert int.from_bytes(data[51:59], "big") == anchors["pinned_block"]
        print(f"{anchor['family']}: {tx_hash} (confirmed, zero-value self-send, {anchor['count']} cases)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        default=Path("reports/evidence/prompt-injection-sepolia-2026-10-20"),
    )
    parser.add_argument("--offline", action="store_true", help="skip public RPC receipt checks")
    parser.add_argument("--rpc-url", default="https://ethereum-sepolia-rpc.publicnode.com")
    args = parser.parse_args()

    directory = args.directory
    corpus = load(directory / "corpus.json")
    results = load(directory / "results.json")
    anchors = load(directory / "anchors.json")
    summary = load(directory / "summary.json")
    source_files = (directory / "agent-source-files.sha256").read_text(encoding="utf-8")

    assert len(corpus) == len(results) == 300
    assert len({item["id"] for item in corpus}) == 300
    assert len({item["id"] for item in results}) == 300
    source_by_id = {item["id"]: item for item in corpus}
    result_by_id = {item["id"]: item for item in results}
    assert source_by_id.keys() == result_by_id.keys()
    assert hashlib.sha256(source_files.encode()).hexdigest() == summary["source_tree_sha256"]
    assert summary["models"]["coordinator"] != summary["models"]["checker"]
    assert summary["model_roles_distinct"] is True
    assert summary["contract_broadcasts_enabled"] is False
    assert summary["agent_signer_present_during_prompts"] is False

    verified = 0
    for anchor in anchors["anchors"]:
        assert anchor["count"] == 50
        assert anchor["value_wei"] == 0 and anchor["sender"].lower() == anchor["recipient"].lower()
        proof_by_id = {item["id"]: item for item in anchor["leaves"]}
        family_records = [item for item in results if item["family"] == anchor["family"]]
        assert len(family_records) == len(proof_by_id) == 50
        for record in family_records:
            assert source_by_id[record["id"]]["prompt"] == record["prompt"]
            assert record["anchor_tx"] == anchor["transaction_hash"]
            assert record["anchor_family_root"] == anchor["merkle_root"]
            assert record["anchor_leaf"] == proof_by_id[record["id"]]["leaf"]
            verify_leaf(record, proof_by_id[record["id"]], anchor["merkle_root"])
            verified += 1

    assert verified == 300
    assert summary["completed"] == 300
    assert summary["finding"] == summary["inconclusive"] == summary["no_broadcast_attempt"] - 300 == 0
    assert sum(len(item.get("broadcast_attempts", [])) for item in results) == 0
    assert not any(any(errors.values()) for item in results for errors in (item.get("model_errors", {}),))
    assert dict(Counter(item["response_type"] for item in results)) == summary["response_types"]
    assert sum(sum(item["model_calls"].values()) for item in results) == summary["model_calls"]
    print(f"Verified {verified}/300 prompt/result records and all six Merkle proofs.")
    print("Recorded outcomes:", dict(Counter(item["response_type"] for item in results)))

    if not args.offline:
        verify_chain(anchors, args.rpc_url)


if __name__ == "__main__":
    main()
