"""Chain indexer, tx builder/simulator and scoped signer (web3.py).

The agent key signs only calls to the buyer's own TiwalaAgentWallet; the contract caps
what that key can do even if everything above it is compromised.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError

from .models import Action, ActionKind, ClosedDeal, Deal, Outcome, Status, WalletState

ABI_DIR = Path(__file__).parent / "abi"
LOG_CHUNK = 9_000  # stay under common public-RPC eth_getLogs block-range limits



TX_GAS_CAP = 16_777_216  # Osaka per-transaction gas cap (EIP-7825)


def with_gas_headroom(tx: dict, factor: float = 1.2) -> dict:
    """build_transaction fills gas from the node's eth_estimateGas, which reflects the live
    fork's pricing (Glamsterdam on Sepolia). Add headroom for state drift; never exceed the cap."""
    if "gas" in tx:
        tx["gas"] = min(int(tx["gas"] * factor), TX_GAS_CAP)
    return tx


def _abi(name: str) -> list:
    return json.loads((ABI_DIR / f"{name}.json").read_text())


WALLET_ABI = _abi("TiwalaAgentWallet")
FACTORY_ABI = _abi("TiwalaFactory")
TOKEN_ABI = _abi("SettlementToken")


def _error_selectors(abi: list) -> dict[str, str]:
    out = {}
    for item in abi:
        if item.get("type") == "error":
            sig = f"{item['name']}({','.join(i['type'] for i in item['inputs'])})"
            out["0x" + Web3.keccak(text=sig).hex().removeprefix("0x")[:8]] = item["name"]
    return out


ERRORS = {**_error_selectors(WALLET_ABI), **_error_selectors(FACTORY_ABI)}


def decode_revert(exc: Exception) -> str:
    data = getattr(exc, "data", None) or (exc.args[1] if len(getattr(exc, "args", ())) > 1 else None)
    text = str(data or exc)
    for sel, name in ERRORS.items():
        if sel[2:] in text.lower():
            return name
    return str(exc)[:200]


@dataclass
class TxResult:
    ok: bool
    tx_hash: Optional[str]
    error: Optional[str] = None
    block: Optional[int] = None


class Chain:
    def __init__(self, rpc_url: str, deployment: dict, agent_key: Optional[str] = None):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        self.dep = deployment
        self.start_block = int(deployment.get("startBlock", 0))
        self.factory = self.w3.eth.contract(address=Web3.to_checksum_address(deployment["factory"]), abi=FACTORY_ABI)
        self.token = self.w3.eth.contract(address=Web3.to_checksum_address(deployment["token"]), abi=TOKEN_ABI)
        self._agent = Account.from_key(agent_key) if agent_key else None
        self._closed_cache: Optional[tuple[int, list[ClosedDeal]]] = None

    # ------------------------------------------------------------- reads

    def wallet(self, address: str):
        return self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=WALLET_ABI)

    def now(self) -> int:
        return int(self.w3.eth.get_block("latest")["timestamp"])

    def is_factory_wallet(self, address: str) -> bool:
        return bool(self.factory.functions.isWallet(Web3.to_checksum_address(address)).call())

    def factory_wallets(self) -> list[str]:
        n = self.factory.functions.walletCount().call()
        return [self.factory.functions.wallets(i).call() for i in range(n)]

    def wallet_state(self, address: str) -> WalletState:
        c = self.wallet(address)
        f = c.functions
        bal = self.token.functions.balanceOf(c.address).call()
        return WalletState(
            address=c.address,
            owner=f.owner().call(),
            agent=f.agent().call(),
            paused=f.paused().call(),
            underfunded=f.isUnderfunded().call(),
            balance=bal,
            locked=f.locked().call(),
            free=f.freeBalance().call(),
            per_deal_cap=f.perDealCap().call(),
            daily_cap=f.dailyCap().call(),
            approval_threshold=f.approvalThreshold().call(),
            max_down_bps=f.maxDownBps().call(),
            grace=f.grace().call(),
            spent_today=f.spentToday().call(),
            current_day=f.currentDay().call(),
            now=self.now(),
        )

    def _logs(self, event, address: str) -> list:
        latest = self.w3.eth.block_number
        out, frm, chunk = [], self.start_block, LOG_CHUNK
        while frm <= latest:
            to = min(latest, frm + chunk)
            try:
                out += event.get_logs(from_block=frm, to_block=to, argument_filters=None)
            except Exception:
                if chunk <= 9:  # some free tiers (Alchemy) allow only 10 blocks per query
                    raise
                chunk = max(9, chunk // 10)
                continue
            frm = to + 1
        return [l for l in out if l["address"].lower() == address.lower()]

    def refs(self, address: str) -> dict[int, str]:
        c = self.wallet(address)
        return {l["args"]["id"]: l["args"]["ref"] for l in self._logs(c.events.DealCreated(), c.address)}

    def deals(self, address: str) -> list[Deal]:
        c = self.wallet(address)
        n = c.functions.nextDealId().call()
        refs = self.refs(address)
        out = []
        for i in range(1, n):
            sup, total, bps, deadline, delivered, status, approved, _ = c.functions.deals(i).call()
            out.append(Deal(c.address, i, sup, total, bps, deadline, delivered, Status(status), approved, refs.get(i, "")))
        return out

    def deal(self, address: str, deal_id: int) -> Optional[Deal]:
        for d in self.deals(address):
            if d.id == deal_id:
                return d
        return None

    def supplier_delay(self, wallet: str) -> int:
        return int(self.wallet(wallet).functions.supplierDelay().call())

    def supplier_onchain(self, wallet: str, supplier: str) -> tuple[bool, int]:
        listed, active_at, _, _ = self.wallet(wallet).functions.suppliers(Web3.to_checksum_address(supplier)).call()
        return bool(listed), int(active_at)

    def closed_deals(self) -> list[ClosedDeal]:
        """Outcomes from every factory wallet, read from events only. Lookalike contracts are ignored."""
        latest = self.w3.eth.block_number
        if self._closed_cache and self._closed_cache[0] == latest:
            return self._closed_cache[1]
        out: list[ClosedDeal] = []
        for addr in self.factory_wallets():
            if not self.is_factory_wallet(addr):
                continue
            c = self.wallet(addr)
            created = {l["args"]["id"]: l["args"] for l in self._logs(c.events.DealCreated(), c.address)}
            for l in self._logs(c.events.BalanceReleased(), c.address):
                a = l["args"]
                out.append(ClosedDeal(c.address, a["supplier"], created[a["id"]]["total"],
                                      Outcome.ON_TIME if a["onTime"] else Outcome.LATE, (l["blockNumber"], l["logIndex"])))
            for l in self._logs(c.events.DealCancelled(), c.address):
                a = l["args"]
                out.append(ClosedDeal(c.address, a["supplier"], created[a["id"]]["total"],
                                      Outcome.NON_DELIVERY if a["afterDownPayment"] else Outcome.NEUTRAL, (l["blockNumber"], l["logIndex"])))
            for l in self._logs(c.events.DisputeResolved(), c.address):
                a = l["args"]
                out.append(ClosedDeal(c.address, a["supplier"], created[a["id"]]["total"],
                                      Outcome.NEUTRAL if a["released"] else Outcome.NON_DELIVERY, (l["blockNumber"], l["logIndex"])))
        out.sort(key=lambda c: c.order)
        self._closed_cache = (latest, out)
        return out

    # ------------------------------------------------------------- writes (agent key only)

    @property
    def agent_address(self) -> Optional[str]:
        return self._agent.address if self._agent else None

    def build_call(self, wallet: str, action: Action):
        f = self.wallet(wallet).functions
        k = action.kind
        if k == ActionKind.CREATE_DEAL:
            return f.createDeal(Web3.to_checksum_address(action.supplier), action.total, action.down_bps,
                                action.deadline, action.ref or "")
        if k == ActionKind.RELEASE_DOWN:
            return f.releaseDownPayment(action.deal_id)
        if k == ActionKind.RELEASE_BALANCE:
            return f.releaseBalance(action.deal_id)
        if k == ActionKind.CANCEL:
            return f.cancelDeal(action.deal_id)
        raise ValueError(f"no call for {k}")

    def simulate(self, wallet: str, action: Action) -> tuple[bool, Optional[str], object]:
        if not self._agent:
            return False, "no agent key configured", None
        call = self.build_call(wallet, action)
        try:
            ret = call.call({"from": self._agent.address})
            return True, None, ret
        except (ContractCustomError, ContractLogicError, ValueError) as e:
            return False, decode_revert(e), None

    def send(self, wallet: str, action: Action) -> TxResult:
        ok, err, _ = self.simulate(wallet, action)
        if not ok:
            return TxResult(False, None, f"simulation reverted: {err}")
        acct = self._agent
        call = self.build_call(wallet, action)
        tx = call.build_transaction({
            "from": acct.address,
            "nonce": self.w3.eth.get_transaction_count(acct.address, "pending"),
            "chainId": self.w3.eth.chain_id,
        })
        tx = with_gas_headroom(tx)
        if tx.get("to", "").lower() != wallet.lower():  # scoped signer: only the buyer's own wallet
            return TxResult(False, None, "signer refused: target is not this buyer's wallet")
        signed = acct.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
        hx = "0x" + h.hex().removeprefix("0x")
        if rcpt["status"] != 1:
            return TxResult(False, hx, "transaction reverted on-chain", rcpt["blockNumber"])
        self._closed_cache = None
        return TxResult(True, hx, None, rcpt["blockNumber"])

    def deal_id_from_receipt(self, wallet: str, tx_hash: str) -> Optional[int]:
        rcpt = self.w3.eth.get_transaction_receipt(tx_hash)
        for ev in self.wallet(wallet).events.DealCreated().process_receipt(rcpt):
            return int(ev["args"]["id"])
        return None


class OwnerConsole:
    """Human-tier actions, signed with the owner's key. Reachable only from explicit user
    commands in the interface (e.g. /attest 3), never from any LLM tool."""

    def __init__(self, chain: Chain, wallet: str, owner_key: str):
        self.chain, self.wallet, self.acct = chain, Web3.to_checksum_address(wallet), Account.from_key(owner_key)

    def _send(self, fn) -> TxResult:
        w3 = self.chain.w3
        try:
            fn.call({"from": self.acct.address})
        except (ContractCustomError, ContractLogicError, ValueError) as e:
            return TxResult(False, None, decode_revert(e))
        tx = fn.build_transaction({"from": self.acct.address, "chainId": w3.eth.chain_id,
                                   "nonce": w3.eth.get_transaction_count(self.acct.address, "pending")})
        tx = with_gas_headroom(tx)
        h = w3.eth.send_raw_transaction(self.acct.sign_transaction(tx).raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        self.chain._closed_cache = None
        return TxResult(r["status"] == 1, "0x" + h.hex().removeprefix("0x"), None, r["blockNumber"])

    def attest(self, deal_id: int) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.confirmDelivery(deal_id))

    def approve(self, deal_id: int) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.approveDeal(deal_id))

    def dispute(self, deal_id: int) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.raiseDispute(deal_id))

    def resolve(self, deal_id: int, release: bool) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.resolveDispute(deal_id, release))

    def add_supplier(self, supplier: str) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.addSupplier(Web3.to_checksum_address(supplier)))

    def remove_supplier(self, supplier: str) -> TxResult:
        return self._send(self.chain.wallet(self.wallet).functions.removeSupplier(Web3.to_checksum_address(supplier)))
